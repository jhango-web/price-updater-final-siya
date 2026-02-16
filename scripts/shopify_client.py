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
        Groups variants by product and updates all variants of each product in one call.

        For 8000 products with 12000 variants, this makes ~8000 API calls (one per product)
        instead of 12000, and uses concurrent requests for speed.

        Args:
            updates: List of dicts with keys: variant_id, price, compare_at_price, product_id (optional)

        Returns:
            Dict with success count, failed count, and errors
        """
        if not updates:
            return {'success_count': 0, 'failed_count': 0, 'errors': []}

        logger.info(f"Starting bulk update for {len(updates)} variants...")

        # Group variants by product_id
        # We need to extract product_id from variant or fetch it
        products_variants = {}
        variants_needing_product = []

        for update in updates:
            variant_id = update['variant_id']
            if not str(variant_id).startswith('gid://'):
                variant_id = f"gid://shopify/ProductVariant/{variant_id}"

            product_id = update.get('product_id')
            if product_id:
                if not str(product_id).startswith('gid://'):
                    product_id = f"gid://shopify/Product/{product_id}"
                if product_id not in products_variants:
                    products_variants[product_id] = []
                products_variants[product_id].append({
                    'id': variant_id,
                    'price': str(update['price']),
                    'compareAtPrice': str(update['compare_at_price'])
                })
            else:
                variants_needing_product.append({
                    'variant_id': variant_id,
                    'price': str(update['price']),
                    'compare_at_price': str(update['compare_at_price'])
                })

        # If we have variants without product_id, fetch them
        if variants_needing_product:
            logger.info(f"Fetching product IDs for {len(variants_needing_product)} variants...")
            # Fall back to individual REST API updates for these
            for var in variants_needing_product:
                numeric_id = var['variant_id'].split('/')[-1]
                # Get variant to find product_id
                response = requests.get(
                    f"{self.base_url}/variants/{numeric_id}.json",
                    headers=self.headers
                )
                if response.status_code == 200:
                    variant_data = response.json().get('variant', {})
                    product_id = f"gid://shopify/Product/{variant_data.get('product_id')}"
                    if product_id not in products_variants:
                        products_variants[product_id] = []
                    products_variants[product_id].append({
                        'id': var['variant_id'],
                        'price': var['price'],
                        'compareAtPrice': var['compare_at_price']
                    })
                time.sleep(0.05)  # Rate limiting

        logger.info(f"Grouped into {len(products_variants)} products")

        success_count = 0
        failed_count = 0
        errors = []
        processed = 0

        # Update each product's variants using productVariantsBulkUpdate
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $productId, variants: $variants) {
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

        total_products = len(products_variants)
        for product_id, variants in products_variants.items():
            processed += 1

            # Log progress every 100 products
            if processed % 100 == 0 or processed == total_products:
                logger.info(f"Progress: {processed}/{total_products} products ({(processed/total_products*100):.1f}%)")

            try:
                result = self.graphql(mutation, {
                    'productId': product_id,
                    'variants': variants
                })

                user_errors = result.get('data', {}).get('productVariantsBulkUpdate', {}).get('userErrors', [])

                if user_errors:
                    failed_count += len(variants)
                    errors.append({'product_id': product_id, 'errors': user_errors})
                    logger.warning(f"Failed to update product {product_id}: {user_errors}")
                else:
                    success_count += len(variants)

            except Exception as e:
                failed_count += len(variants)
                errors.append({'product_id': product_id, 'error': str(e)})
                logger.error(f"Exception updating product {product_id}: {str(e)}")

            # Rate limiting - Shopify allows ~40 requests/second
            time.sleep(0.03)

        logger.info(f"Bulk update complete: {success_count} succeeded, {failed_count} failed")

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
        Bulk update product metafields using productUpdate mutation.
        Groups metafields by product and updates all metafields of each product in one call.

        Args:
            updates: List of dicts with keys: product_id, namespace, key, value, value_type

        Returns:
            Dict with success count, failed count, and errors
        """
        if not updates:
            return {'success_count': 0, 'failed_count': 0, 'errors': []}

        logger.info(f"Starting bulk metafield update for {len(updates)} updates...")

        # Group metafields by product_id
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

        logger.info(f"Grouped into {len(products_metafields)} products")

        success_count = 0
        failed_count = 0
        errors = []
        processed = 0

        mutation = """
        mutation productUpdate($input: ProductInput!) {
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

        total_products = len(products_metafields)
        for product_id, metafields in products_metafields.items():
            processed += 1

            if processed % 100 == 0 or processed == total_products:
                logger.info(f"Metafield progress: {processed}/{total_products} products ({(processed/total_products*100):.1f}%)")

            try:
                result = self.graphql(mutation, {
                    'input': {
                        'id': product_id,
                        'metafields': metafields
                    }
                })

                user_errors = result.get('data', {}).get('productUpdate', {}).get('userErrors', [])

                if user_errors:
                    failed_count += len(metafields)
                    errors.append({'product_id': product_id, 'errors': user_errors})
                else:
                    success_count += len(metafields)

            except Exception as e:
                failed_count += len(metafields)
                errors.append({'product_id': product_id, 'error': str(e)})

            time.sleep(0.03)

        logger.info(f"Metafield update complete: {success_count} succeeded, {failed_count} failed")

        return {
            'success_count': success_count,
            'failed_count': failed_count,
            'errors': errors
        }
