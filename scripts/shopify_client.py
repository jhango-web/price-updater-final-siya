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
        Bulk update variant prices using productVariantsBulkUpdate mutation.

        Args:
            updates: List of dicts with keys: variant_id, price, compare_at_price

        Returns:
            Dict with success count, failed count, and errors
        """
        # Group updates by product for efficiency
        products_map = {}
        for update in updates:
            variant_id = update['variant_id']
            # Extract product ID from variant ID (format: gid://shopify/ProductVariant/123)
            # We need to get the product ID separately, so we'll batch by chunks
            products_map[variant_id] = update

        success_count = 0
        failed_count = 0
        errors = []

        # Process in batches of 100 variants
        batch_size = 100
        variant_ids = list(products_map.keys())

        for i in range(0, len(variant_ids), batch_size):
            batch = variant_ids[i:i + batch_size]

            mutation = """
            mutation bulkUpdateVariants($input: [ProductVariantsBulkInput!]!, $productId: ID!) {
                productVariantsBulkUpdate(variants: $input, productId: $productId) {
                    productVariants {
                        id
                        price
                        compareAtPrice
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """

            # For bulk operations we need to update one product at a time
            # Group variants by product first
            for variant_id in batch:
                update = products_map[variant_id]

                # Use direct variant update for individual updates
                single_mutation = """
                mutation updateVariant($input: ProductVariantInput!) {
                    productVariantUpdate(input: $input) {
                        productVariant {
                            id
                            price
                            compareAtPrice
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
                        'id': variant_id,
                        'price': str(update['price']),
                        'compareAtPrice': str(update['compare_at_price'])
                    }
                }

                try:
                    result = self.graphql(single_mutation, variables)
                    user_errors = result.get('data', {}).get('productVariantUpdate', {}).get('userErrors', [])

                    if user_errors:
                        failed_count += 1
                        errors.append({'variant_id': variant_id, 'errors': user_errors})
                    else:
                        success_count += 1
                except Exception as e:
                    failed_count += 1
                    errors.append({'variant_id': variant_id, 'error': str(e)})

                # Rate limiting
                time.sleep(0.1)

        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'errors': errors
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
        Bulk update product metafields.

        Args:
            updates: List of dicts with keys: product_id, namespace, key, value, value_type

        Returns:
            Dict with success count, failed count, and errors
        """
        success_count = 0
        failed_count = 0
        errors = []

        for update in updates:
            try:
                success = self.update_product_metafield(
                    update['product_id'],
                    update['namespace'],
                    update['key'],
                    update['value'],
                    update['value_type']
                )
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append({'product_id': update['product_id'], 'error': 'Unknown error'})
            except Exception as e:
                failed_count += 1
                errors.append({'product_id': update['product_id'], 'error': str(e)})

            time.sleep(0.1)

        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'errors': errors
        }
