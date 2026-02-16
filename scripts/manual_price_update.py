#!/usr/bin/env python3
"""
Manual Price Update Script
==========================
Allows manual entry of gold/silver prices with include/exclude product handles.
Updates theme settings if all products are selected.
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional

from price_calculator import GoldPriceCalculator, SilverPriceCalculator
from shopify_client import ShopifyClient
from email_notifier import EmailNotifier

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def parse_handles(handles_str: str) -> Set[str]:
    """Parse comma or newline separated handles into a set."""
    if not handles_str:
        return set()
    # Split by comma or newline, strip whitespace, remove empty
    handles = set()
    for line in handles_str.replace(',', '\n').split('\n'):
        handle = line.strip()
        if handle:
            handles.add(handle)
    return handles


def is_gold_product(product: Dict) -> bool:
    """Determine if a product is gold based on variants."""
    variants = product.get('variants', {}).get('edges', [])
    for variant_edge in variants:
        variant = variant_edge['node']
        title = variant.get('title', '').upper()
        if any(purity in title for purity in ['9KT', '10KT', '14KT', '18KT', '22KT', '24KT', '9K', '10K', '14K', '18K', '22K', '24K']):
            return True
    return False


def is_silver_product(product: Dict) -> bool:
    """Determine if a product is silver based on variants."""
    variants = product.get('variants', {}).get('edges', [])
    for variant_edge in variants:
        variant = variant_edge['node']
        title = variant.get('title', '').upper()
        if 'SILVER' in title or '925' in title or 'STERLING' in title:
            return True
    return False


def get_metafield_value(metafields: Dict, key: str, default=0):
    """Get metafield value by key."""
    value = metafields.get(key, default)
    if isinstance(value, str):
        try:
            if value.startswith('['):
                parsed = json.loads(value)
                if parsed:
                    return float(parsed[0]) if isinstance(parsed[0], (int, float, str)) else default
            return float(value)
        except (ValueError, json.JSONDecodeError):
            return default
    return float(value) if value else default


def filter_products(
    products: List[Dict],
    include_handles: Set[str],
    exclude_handles: Set[str]
) -> Tuple[List[Dict], bool]:
    """
    Filter products based on include/exclude handles.
    Exclude takes precedence over include.

    Returns:
        Tuple of (filtered_products, is_all_products)
    """
    # If no include handles specified, include all
    if not include_handles:
        filtered = [p for p in products if p['handle'] not in exclude_handles]
        is_all = len(exclude_handles) == 0
    else:
        # Include only specified handles, then apply exclude
        filtered = [
            p for p in products
            if p['handle'] in include_handles and p['handle'] not in exclude_handles
        ]
        # Check if effectively all products are included
        total_handles = {p['handle'] for p in products}
        included_handles = include_handles - exclude_handles
        is_all = included_handles == total_handles

    return filtered, is_all


def process_products(
    client: ShopifyClient,
    products: List[Dict],
    gold_rate: Optional[float],
    silver_rate: Optional[float],
    diamond_configs: Dict,
    gst_percentage: float
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Process products and calculate new prices."""
    gold_calculator = GoldPriceCalculator(gold_rate, gst_percentage, diamond_configs) if gold_rate else None
    silver_calculator = SilverPriceCalculator(silver_rate) if silver_rate else None

    updates = []
    details = []
    metafield_updates = []

    for product in products:
        product_id = product['id']
        product_title = product['title']
        handle = product['handle']

        metafields = {
            f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
            for mf in product.get('metafields', {}).get('edges', [])
        }

        is_gold = is_gold_product(product)
        is_silver = is_silver_product(product)

        # Skip if no applicable calculator
        if is_gold and not gold_calculator:
            logger.info(f"Skipping gold product {handle} (no gold rate provided)")
            continue
        if is_silver and not silver_calculator:
            logger.info(f"Skipping silver product {handle} (no silver rate provided)")
            continue
        if not is_gold and not is_silver:
            logger.info(f"Skipping product {handle} (not gold or silver)")
            continue

        # Update rate metafield
        if is_gold and gold_rate:
            metafield_updates.append({
                'product_id': product_id,
                'namespace': 'jhango',
                'key': 'gold_rate',
                'value': str(gold_rate),
                'value_type': 'number_decimal'
            })
        if is_silver and silver_rate:
            metafield_updates.append({
                'product_id': product_id,
                'namespace': 'jhango',
                'key': 'silver_rate',
                'value': str(silver_rate),
                'value_type': 'number_decimal'
            })

        # Get product-level values
        making_charge_percentage = get_metafield_value(metafields, 'custom.making_charge_percentage', 0)
        discount_percentage = get_metafield_value(metafields, 'custom.discount_making_charge', 0)
        hallmarking = get_metafield_value(metafields, 'jhango.hallmarking', 0)
        certification = get_metafield_value(metafields, 'jhango.certification', 0)
        product_stone_carats = get_metafield_value(metafields, 'custom.stone_carats', 0)
        product_stone_type = metafields.get('custom.stone_types', '')
        product_stone_price = get_metafield_value(metafields, 'custom.stone_prices_per_carat', 0)
        product_metal_weight = get_metafield_value(metafields, 'custom.metal_weight', 0)

        # Process variants
        for variant_edge in product.get('variants', {}).get('edges', []):
            variant = variant_edge['node']
            variant_id = variant['id']
            variant_title = variant.get('title', '')
            old_price = variant.get('price', '0')

            variant_metafields = {
                f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
                for mf in variant.get('metafields', {}).get('edges', [])
            }

            metal_weight = get_metafield_value(variant_metafields, 'custom.metal_weight', product_metal_weight)
            stone_carats = get_metafield_value(variant_metafields, 'custom.stone_carats', product_stone_carats)
            stone_type = variant_metafields.get('custom.stone_types', product_stone_type)
            stone_price = get_metafield_value(variant_metafields, 'custom.stone_prices_per_carat', product_stone_price)

            if is_gold:
                price, compare_at_price, _ = gold_calculator.calculate(
                    metal_weight=metal_weight,
                    purity_value=variant_title,
                    stone_carats=stone_carats,
                    stone_type=stone_type,
                    stone_price_per_carat=stone_price,
                    making_charge_percentage=making_charge_percentage,
                    hallmarking_charge=hallmarking,
                    certification_charge=certification,
                    discount_making_charge=discount_percentage
                )
            else:
                price, compare_at_price, _ = silver_calculator.calculate(metal_weight, stone_carats)

            updates.append({
                'variant_id': variant_id,
                'product_id': product_id,
                'price': price,
                'compare_at_price': compare_at_price
            })

            details.append({
                'product_title': product_title,
                'variant_title': variant_title,
                'old_price': old_price,
                'new_price': str(price),
                'compare_at_price': str(compare_at_price)
            })

            logger.info(f"  {product_title} / {variant_title}: ₹{old_price} -> ₹{price}")

    return updates, details, metafield_updates


def main():
    """Main entry point for manual price update."""
    # Get configuration from environment
    shop_url = os.environ.get('SHOPIFY_SHOP_URL')
    access_token = os.environ.get('SHOPIFY_ACCESS_TOKEN')
    theme_id = os.environ.get('SHOPIFY_THEME_ID')

    # Manual price inputs
    gold_rate_str = os.environ.get('GOLD_RATE', '')
    silver_rate_str = os.environ.get('SILVER_RATE', '')

    # Include/exclude handles
    include_handles_str = os.environ.get('INCLUDE_HANDLES', '')
    exclude_handles_str = os.environ.get('EXCLUDE_HANDLES', '')

    if not all([shop_url, access_token]):
        logger.error("Missing required environment variables: SHOPIFY_SHOP_URL, SHOPIFY_ACCESS_TOKEN")
        sys.exit(1)

    if not gold_rate_str and not silver_rate_str:
        logger.error("At least one of GOLD_RATE or SILVER_RATE must be provided")
        sys.exit(1)

    gold_rate = float(gold_rate_str) if gold_rate_str else None
    silver_rate = float(silver_rate_str) if silver_rate_str else None
    theme_id = int(theme_id) if theme_id else None

    include_handles = parse_handles(include_handles_str)
    exclude_handles = parse_handles(exclude_handles_str)

    logger.info("=" * 60)
    logger.info("MANUAL PRICE UPDATE")
    logger.info("=" * 60)
    logger.info(f"\nPrices:")
    if gold_rate:
        logger.info(f"  Gold (24K): ₹{gold_rate}/gram")
    if silver_rate:
        logger.info(f"  Silver: ₹{silver_rate}/gram")

    if include_handles:
        logger.info(f"\nInclude handles ({len(include_handles)}): {', '.join(list(include_handles)[:10])}{'...' if len(include_handles) > 10 else ''}")
    if exclude_handles:
        logger.info(f"Exclude handles ({len(exclude_handles)}): {', '.join(list(exclude_handles)[:10])}{'...' if len(exclude_handles) > 10 else ''}")

    # Initialize client
    client = ShopifyClient(shop_url, access_token, theme_id)

    # Get diamond configs and GST from theme
    settings = client.get_theme_settings()
    diamond_configs = client.get_diamond_configs(settings)
    gst_percentage = float(settings.get('gst_percentage', 3))

    # Fetch all products
    logger.info("\nFetching products...")
    all_products = client.get_all_products()
    logger.info(f"Found {len(all_products)} total products")

    # Filter products
    filtered_products, is_all_products = filter_products(all_products, include_handles, exclude_handles)
    logger.info(f"Processing {len(filtered_products)} products (all: {is_all_products})")

    if not filtered_products:
        logger.warning("No products to process after filtering")
        sys.exit(0)

    # Update theme settings if all products are being updated
    if is_all_products:
        logger.info("\nUpdating theme settings (all products selected)...")
        theme_updates = {}
        if gold_rate:
            theme_updates['gold_rate'] = gold_rate
        if silver_rate:
            theme_updates['silver_rate'] = silver_rate
        if theme_updates:
            client.update_theme_settings(theme_updates)
            logger.info("Theme settings updated")
    else:
        logger.info("\nSkipping theme settings update (subset of products selected)")

    # Process products
    logger.info("\nProcessing products...")
    updates, details, metafield_updates = process_products(
        client, filtered_products, gold_rate, silver_rate, diamond_configs, gst_percentage
    )

    logger.info(f"\nTotal updates: {len(updates)} variants, {len(metafield_updates)} metafields")

    # Apply updates
    logger.info("\nApplying price updates...")
    price_result = client.bulk_update_variant_prices(updates)
    logger.info(f"Price updates: {price_result['success_count']} succeeded, {price_result['failed_count']} failed")

    logger.info("\nApplying metafield updates...")
    metafield_result = client.bulk_update_product_metafields(metafield_updates)
    logger.info(f"Metafield updates: {metafield_result['success_count']} succeeded, {metafield_result['failed_count']} failed")

    # Build summary
    summary = {
        'gold_rate': f"₹{gold_rate}/gram" if gold_rate else "Not updated",
        'silver_rate': f"₹{silver_rate}/gram" if silver_rate else "Not updated",
        'total_products_in_store': len(all_products),
        'products_processed': len(filtered_products),
        'theme_settings_updated': is_all_products,
        'variants_updated_success': price_result['success_count'],
        'variants_updated_failed': price_result['failed_count'],
        'metafields_updated_success': metafield_result['success_count'],
        'metafields_updated_failed': metafield_result['failed_count']
    }

    # Send email notification
    logger.info("\nSending email notification...")
    notifier = EmailNotifier()
    all_errors = price_result.get('errors', []) + metafield_result.get('errors', [])
    notifier.send_report(
        subject=f"[Shopify] Manual Price Update - {datetime.now().strftime('%Y-%m-%d')}",
        workflow_type="Manual Price Update",
        summary=summary,
        details=details,
        errors=all_errors if all_errors else None
    )

    logger.info("\n" + "=" * 60)
    logger.info("MANUAL PRICE UPDATE COMPLETE")
    logger.info("=" * 60)

    if price_result['failed_count'] > 0 or metafield_result['failed_count'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
