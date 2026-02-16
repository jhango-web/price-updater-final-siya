#!/usr/bin/env python3
"""
Shopify Client Module
=====================
Handles Shopify API interactions with efficient bulk operations.
"""

import json
import time
import requests
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class ShopifyClient:
    """Efficient Shopify API client using GraphQL bulk operations."""

    def __init__(self, shop_url: str, access_token: str, theme_id: Optional[int] = None):
        self.shop_url = shop_url.rstrip('/')
        self.access_token = access_token
        self.theme_id = theme_id
        self.base_url = f"https://{self.shop_url}/admin/api/2024-01"
        self.graphql_url = f"https://{self.shop_url}/admin/api/2024-01/graphql.json"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }

    def graphql(self, query: str, variables: Dict = None) -> Dict:
        """Execute a GraphQL query."""
        payload = {'query': query}
        if variables:
            payload['variables'] = variables

        response = requests.post(self.graphql_url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    def get_theme_settings(self) -> Dict:
        """Fetch theme settings from settings_data.json."""
        theme_id = self.theme_id
        if not theme_id:
            # Get main theme
            response = requests.get(f"{self.base_url}/themes.json", headers=self.headers)
            response.raise_for_status()
            themes = response.json().get('themes', [])
            for theme in themes:
                if theme.get('role') == 'main':
                    theme_id = theme['id']
                    break

        if not theme_id:
            raise Exception("No main theme found")

        # Get settings_data.json
        response = requests.get(
            f"{self.base_url}/themes/{theme_id}/assets.json",
            headers=self.headers,
            params={"asset[key]": "config/settings_data.json"}
        )
        response.raise_for_status()

        settings_data = json.loads(response.json()['asset']['value'])
        return settings_data.get('current', {})

    def update_theme_settings(self, updates: Dict) -> bool:
        """Update theme settings in settings_data.json."""
        theme_id = self.theme_id
        if not theme_id:
            response = requests.get(f"{self.base_url}/themes.json", headers=self.headers)
            response.raise_for_status()
            themes = response.json().get('themes', [])
            for theme in themes:
                if theme.get('role') == 'main':
                    theme_id = theme['id']
                    break

        if not theme_id:
            raise Exception("No main theme found")

        # Get current settings
        response = requests.get(
            f"{self.base_url}/themes/{theme_id}/assets.json",
            headers=self.headers,
            params={"asset[key]": "config/settings_data.json"}
        )
        response.raise_for_status()

        settings_data = json.loads(response.json()['asset']['value'])
        current = settings_data.get('current', {})

        # Apply updates
        for key, value in updates.items():
            current[key] = value

        settings_data['current'] = current

        # Save updated settings
        response = requests.put(
            f"{self.base_url}/themes/{theme_id}/assets.json",
            headers=self.headers,
            json={
                "asset": {
                    "key": "config/settings_data.json",
                    "value": json.dumps(settings_data, indent=2)
                }
            }
        )
        response.raise_for_status()
        return True

    def get_diamond_configs(self, settings: Dict) -> Dict[str, float]:
        """Extract diamond configurations from theme settings."""
        diamond_configs = {}
        for i in range(1, 21):
            name = settings.get(f'diamond_{i}_name', '').strip()
            if not name:
                break
            price = float(settings.get(f'diamond_{i}_price_per_carat', 0))
            diamond_configs[name.lower()] = price
        return diamond_configs

    def get_all_products(self, handles: List[str] = None) -> List[Dict]:
        """
        Fetch all products with their metafields and variants.
        If handles provided, only fetch those products.
        """
        products = []
        cursor = None
        has_next = True

        while has_next:
            query = """
            query getProducts($cursor: String, $query: String) {
                products(first: 50, after: $cursor, query: $query) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        node {
                            id
                            handle
                            title
                            productType
                            metafields(first: 50) {
                                edges {
                                    node {
                                        namespace
                                        key
                                        value
                                        type
                                    }
                                }
                            }
                            variants(first: 100) {
                                edges {
                                    node {
                                        id
                                        title
                                        price
                                        compareAtPrice
                                        sku
                                        metafields(first: 20) {
                                            edges {
                                                node {
                                                    namespace
                                                    key
                                                    value
                                                    type
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """

            variables = {'cursor': cursor}
            if handles:
                # Build OR query for handles
                handle_queries = [f'handle:{h}' for h in handles]
                variables['query'] = ' OR '.join(handle_queries)

            result = self.graphql(query, variables)
            data = result.get('data', {}).get('products', {})

            for edge in data.get('edges', []):
                products.append(edge['node'])

            page_info = data.get('pageInfo', {})
            has_next = page_info.get('hasNextPage', False)
            cursor = page_info.get('endCursor')

            # Rate limiting
            time.sleep(0.2)

        return products

    def get_products_by_stone_types(self, stone_types: List[str]) -> List[Dict]:
        """Fetch products that have specific stone types (case-insensitive)."""
        all_products = self.get_all_products()
        matching_products = []

        stone_types_lower = [st.lower() for st in stone_types]

        for product in all_products:
            metafields = {
                f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
                for mf in product.get('metafields', {}).get('edges', [])
            }

            product_stone_types = metafields.get('custom.stone_types', '')
            if product_stone_types:
                product_stones = [s.strip().lower() for s in product_stone_types.split(',')]
                if any(st in stone_types_lower for st in product_stones):
                    matching_products.append(product)

        return matching_products

    def bulk_update_variant_prices(self, updates: List[Dict]) -> Dict:
        """
        Bulk update variant prices using Shopify Bulk Operations API.
        This handles thousands of variants efficiently in a single async operation.

        Args:
            updates: List of dicts with keys: variant_id, price, compare_at_price

        Returns:
            Dict with success count, failed count, and errors
        """
        if not updates:
            return {'success_count': 0, 'failed_count': 0, 'errors': []}

        logger.info(f"Starting bulk update for {len(updates)} variants using Bulk Operations API...")

        # Step 1: Create JSONL content for bulk mutation
        jsonl_lines = []
        for update in updates:
            variant_id = update['variant_id']
            # Ensure GID format
            if not str(variant_id).startswith('gid://'):
                variant_id = f"gid://shopify/ProductVariant/{variant_id}"

            line = json.dumps({
                "input": {
                    "id": variant_id,
                    "price": str(update['price']),
                    "compareAtPrice": str(update['compare_at_price'])
                }
            })
            jsonl_lines.append(line)

        jsonl_content = '\n'.join(jsonl_lines)
        logger.info(f"Created JSONL with {len(jsonl_lines)} lines")

        # Step 2: Stage the upload
        stage_mutation = """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
            stagedUploadsCreate(input: $input) {
                stagedTargets {
                    url
                    resourceUrl
                    parameters {
                        name
                        value
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        stage_result = self.graphql(stage_mutation, {
            "input": [{
                "resource": "BULK_MUTATION_VARIABLES",
                "filename": "bulk_variants.jsonl",
                "mimeType": "text/jsonl",
                "httpMethod": "POST"
            }]
        })

        stage_errors = stage_result.get('data', {}).get('stagedUploadsCreate', {}).get('userErrors', [])
        if stage_errors:
            logger.error(f"Stage upload errors: {stage_errors}")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': stage_errors}

        staged_target = stage_result.get('data', {}).get('stagedUploadsCreate', {}).get('stagedTargets', [{}])[0]
        upload_url = staged_target.get('url')
        resource_url = staged_target.get('resourceUrl')
        parameters = staged_target.get('parameters', [])

        if not upload_url:
            logger.error("No upload URL returned from staged upload")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': [{'error': 'No upload URL'}]}

        logger.info(f"Got staged upload URL, uploading JSONL file...")

        # Step 3: Upload the JSONL file to staged URL
        form_data = {param['name']: param['value'] for param in parameters}
        files = {'file': ('bulk_variants.jsonl', jsonl_content.encode('utf-8'), 'text/jsonl')}

        upload_response = requests.post(upload_url, data=form_data, files=files)
        if upload_response.status_code not in [200, 201, 204]:
            logger.error(f"Upload failed: {upload_response.status_code} - {upload_response.text}")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': [{'error': upload_response.text}]}

        logger.info("JSONL file uploaded successfully to staged URL")

        # Step 4: Run the bulk mutation
        bulk_mutation = """
        mutation bulkOperationRunMutation($mutation: String!, $stagedUploadPath: String!) {
            bulkOperationRunMutation(mutation: $mutation, stagedUploadPath: $stagedUploadPath) {
                bulkOperation {
                    id
                    status
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        mutation_str = """
            mutation call($input: ProductVariantInput!) {
                productVariantUpdate(input: $input) {
                    productVariant {
                        id
                        price
                        compareAtPrice
                    }
                    userErrors {
                        message
                        field
                    }
                }
            }
        """

        bulk_result = self.graphql(bulk_mutation, {
            "mutation": mutation_str,
            "stagedUploadPath": resource_url
        })

        bulk_errors = bulk_result.get('data', {}).get('bulkOperationRunMutation', {}).get('userErrors', [])
        if bulk_errors:
            logger.error(f"Bulk mutation errors: {bulk_errors}")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': bulk_errors}

        bulk_op = bulk_result.get('data', {}).get('bulkOperationRunMutation', {}).get('bulkOperation', {})
        bulk_op_id = bulk_op.get('id')
        logger.info(f"Bulk operation started: {bulk_op_id}")

        # Step 5: Poll for completion
        poll_query = """
        query {
            currentBulkOperation(type: MUTATION) {
                id
                status
                errorCode
                objectCount
                fileSize
                url
                completedAt
            }
        }
        """

        max_polls = 180  # Max 15 minutes (180 * 5 seconds)
        for i in range(max_polls):
            time.sleep(5)  # Poll every 5 seconds

            poll_result = self.graphql(poll_query)
            current_op = poll_result.get('data', {}).get('currentBulkOperation', {})

            if not current_op:
                logger.warning("No current bulk operation found, continuing to poll...")
                continue

            status = current_op.get('status')
            object_count = current_op.get('objectCount', 0)
            logger.info(f"Bulk operation status: {status} | Processed: {object_count} objects (poll {i+1})")

            if status == 'COMPLETED':
                logger.info(f"Bulk operation completed! Processed {object_count} objects")
                return {
                    'success_count': len(updates),
                    'failed_count': 0,
                    'errors': []
                }
            elif status == 'FAILED':
                error_code = current_op.get('errorCode', 'Unknown error')
                logger.error(f"Bulk operation failed: {error_code}")
                return {
                    'success_count': 0,
                    'failed_count': len(updates),
                    'errors': [{'error': error_code}]
                }
            elif status in ['CANCELED', 'EXPIRED']:
                logger.error(f"Bulk operation {status}")
                return {
                    'success_count': 0,
                    'failed_count': len(updates),
                    'errors': [{'error': status}]
                }

        logger.error("Bulk operation timed out after 15 minutes")
        return {
            'success_count': 0,
            'failed_count': len(updates),
            'errors': [{'error': 'Operation timed out'}]
        }

    def update_product_metafield(self, product_id: str, namespace: str, key: str, value: Any, value_type: str) -> bool:
        """Update a single metafield on a product."""
        mutation = """
        mutation updateMetafield($input: ProductInput!) {
            productUpdate(input: $input) {
                product {
                    id
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        variables = {
            'input': {
                'id': product_id,
                'metafields': [{
                    'namespace': namespace,
                    'key': key,
                    'value': str(value),
                    'type': value_type
                }]
            }
        }

        result = self.graphql(mutation, variables)
        user_errors = result.get('data', {}).get('productUpdate', {}).get('userErrors', [])
        return len(user_errors) == 0

    def bulk_update_product_metafields(self, updates: List[Dict]) -> Dict:
        """
        Bulk update product metafields using Shopify Bulk Operations API.

        Args:
            updates: List of dicts with keys: product_id, namespace, key, value, value_type

        Returns:
            Dict with success count, failed count, and errors
        """
        if not updates:
            return {'success_count': 0, 'failed_count': 0, 'errors': []}

        logger.info(f"Starting bulk metafield update for {len(updates)} products...")

        # Step 1: Create JSONL content - group by product_id
        products_metafields = {}
        for update in updates:
            product_id = update['product_id']
            if not str(product_id).startswith('gid://'):
                product_id = f"gid://shopify/Product/{product_id}"

            if product_id not in products_metafields:
                products_metafields[product_id] = []

            products_metafields[product_id].append({
                'namespace': update['namespace'],
                'key': update['key'],
                'value': str(update['value']),
                'type': update['value_type']
            })

        jsonl_lines = []
        for product_id, metafields in products_metafields.items():
            line = json.dumps({
                "input": {
                    "id": product_id,
                    "metafields": metafields
                }
            })
            jsonl_lines.append(line)

        jsonl_content = '\n'.join(jsonl_lines)
        logger.info(f"Created JSONL with {len(jsonl_lines)} products")

        # Step 2: Stage the upload
        stage_mutation = """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
            stagedUploadsCreate(input: $input) {
                stagedTargets {
                    url
                    resourceUrl
                    parameters {
                        name
                        value
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        stage_result = self.graphql(stage_mutation, {
            "input": [{
                "resource": "BULK_MUTATION_VARIABLES",
                "filename": "bulk_metafields.jsonl",
                "mimeType": "text/jsonl",
                "httpMethod": "POST"
            }]
        })

        stage_errors = stage_result.get('data', {}).get('stagedUploadsCreate', {}).get('userErrors', [])
        if stage_errors:
            logger.error(f"Stage upload errors: {stage_errors}")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': stage_errors}

        staged_target = stage_result.get('data', {}).get('stagedUploadsCreate', {}).get('stagedTargets', [{}])[0]
        upload_url = staged_target.get('url')
        resource_url = staged_target.get('resourceUrl')
        parameters = staged_target.get('parameters', [])

        if not upload_url:
            logger.error("No upload URL returned")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': [{'error': 'No upload URL'}]}

        # Step 3: Upload the JSONL file
        form_data = {param['name']: param['value'] for param in parameters}
        files = {'file': ('bulk_metafields.jsonl', jsonl_content.encode('utf-8'), 'text/jsonl')}

        upload_response = requests.post(upload_url, data=form_data, files=files)
        if upload_response.status_code not in [200, 201, 204]:
            logger.error(f"Upload failed: {upload_response.status_code}")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': [{'error': upload_response.text}]}

        logger.info("JSONL file uploaded for metafields")

        # Step 4: Run the bulk mutation
        bulk_mutation = """
        mutation bulkOperationRunMutation($mutation: String!, $stagedUploadPath: String!) {
            bulkOperationRunMutation(mutation: $mutation, stagedUploadPath: $stagedUploadPath) {
                bulkOperation {
                    id
                    status
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        mutation_str = """
            mutation call($input: ProductInput!) {
                productUpdate(input: $input) {
                    product {
                        id
                    }
                    userErrors {
                        message
                        field
                    }
                }
            }
        """

        bulk_result = self.graphql(bulk_mutation, {
            "mutation": mutation_str,
            "stagedUploadPath": resource_url
        })

        bulk_errors = bulk_result.get('data', {}).get('bulkOperationRunMutation', {}).get('userErrors', [])
        if bulk_errors:
            logger.error(f"Bulk mutation errors: {bulk_errors}")
            return {'success_count': 0, 'failed_count': len(updates), 'errors': bulk_errors}

        bulk_op = bulk_result.get('data', {}).get('bulkOperationRunMutation', {}).get('bulkOperation', {})
        logger.info(f"Bulk metafield operation started: {bulk_op.get('id')}")

        # Step 5: Poll for completion
        poll_query = """
        query {
            currentBulkOperation(type: MUTATION) {
                id
                status
                errorCode
                objectCount
                completedAt
            }
        }
        """

        max_polls = 180
        for i in range(max_polls):
            time.sleep(5)

            poll_result = self.graphql(poll_query)
            current_op = poll_result.get('data', {}).get('currentBulkOperation', {})

            if not current_op:
                continue

            status = current_op.get('status')
            object_count = current_op.get('objectCount', 0)
            logger.info(f"Metafield bulk status: {status} | Processed: {object_count} (poll {i+1})")

            if status == 'COMPLETED':
                logger.info(f"Metafield bulk completed! Processed {object_count} products")
                return {'success_count': len(updates), 'failed_count': 0, 'errors': []}
            elif status in ['FAILED', 'CANCELED', 'EXPIRED']:
                error_code = current_op.get('errorCode', status)
                return {'success_count': 0, 'failed_count': len(updates), 'errors': [{'error': error_code}]}

        return {'success_count': 0, 'failed_count': len(updates), 'errors': [{'error': 'Timed out'}]}
