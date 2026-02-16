#!/usr/bin/env python3
"""
Diamond Price Update Script
===========================
Updates diamond prices and recalculates all affected products.
Can use theme settings or manually entered diamond prices.
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set

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


def parse_diamond_configs(config_str: str) -> Dict[str, float]:
    """
    Parse diamond configurations from JSON string or key:value pairs.

    Formats supported:
    - JSON: {"diamond_type": 1000, "another_type": 2000}
    - Key:Value pairs: diamond_type:1000,another_type:2000
    """
    if not config_str:
        return {}

    config_str = config_str.strip()

    # Try JSON first
    if config_str.startswith('{'):
        try:
            parsed = json.loads(config_str)
            # Normalize keys to lowercase
            return {k.lower(): float(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass

    # Try key:value pairs
    configs = {}
    for pair in config_str.split(','):
        if ':' in pair:
            key, value = pair.split(':', 1)
            key = key.strip().lower()
            try:
                configs[key] = float(value.strip())
            except ValueError:
                logger.warning(f"Invalid diamond price value: {pair}")
    return configs


def is_gold_product(product: Dict) -> bool:
    """Determine if a product is gold based on variants."""
    variants = product.get('variants', {}).get('edges', [])
    for variant_edge in variants:
        variant = variant_edge['node']
        title = variant.get('title', '').upper()
        if any(purity in title for purity in ['9KT', '10KT', '14KT', '18KT', '22KT', '24KT', '9K', '10K', '14K', '18K', '22K', '24K']):
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


def find_affected_products(products: List[Dict], diamond_types: Set[str]) -> List[Dict]:
    """
    Find products that have stone types matching the updated diamond types.
    Case-insensitive matching.
    """
    affected = []
    diamond_types_lower = {dt.lower() for dt in diamond_types}

    for product in products:
        metafields = {
            f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
            for mf in product.get('metafields', {}).get('edges', [])
        }

        # Check product-level stone types
        product_stone_types = metafields.get('custom.stone_types', '')
        if product_stone_types:
            stones = [s.strip().lower() for s in product_stone_types.split(',')]
            if any(st in diamond_types_lower for st in stones):
                affected.append(product)
                continue

        # Check variant-level stone types
        for variant_edge in product.get('variants', {}).get('edges', []):
            variant = variant_edge['node']
            variant_metafields = {
                f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
                for mf in variant.get('metafields', {}).get('edges', [])
            }
            variant_stone_types = variant_metafields.get('custom.stone_types', '')
            if variant_stone_types:
                stones = [s.strip().lower() for s in variant_stone_types.split(',')]
                if any(st in diamond_types_lower for st in stones):
                    affected.append(product)
                    break

    return affected


def process_products(
    client: ShopifyClient,
    products: List[Dict],
    diamond_configs: Dict,
    gold_rate: float,
    gst_percentage: float
) -> Tuple[List[Dict], List[Dict]]:
    """Process gold products and recalculate prices with updated diamond prices."""
    calculator = GoldPriceCalculator(gold_rate, gst_percentage, diamond_configs)
    updates = []
    details = []

    for product in products:
        if not is_gold_product(product):
            continue

        product_id = product['id']
        product_title = product['title']

        metafields = {
            f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
            for mf in product.get('metafields', {}).get('edges', [])
        }

        making_charge_percentage = get_metafield_value(metafields, 'custom.making_charge_percentage', 0)
        discount_percentage = get_metafield_value(metafields, 'custom.discount_making_charge', 0)
        hallmarking = get_metafield_value(metafields, 'jhango.hallmarking', 0)
        certification = get_metafield_value(metafields, 'jhango.certification', 0)
        product_stone_carats = get_metafield_value(metafields, 'custom.stone_carats', 0)
        product_stone_type = metafields.get('custom.stone_types', '')
        product_stone_price = get_metafield_value(metafields, 'custom.stone_prices_per_carat', 0)
        product_metal_weight = get_metafield_value(metafields, 'custom.metal_weight', 0)

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

            price, compare_at_price, _ = calculator.calculate(
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

            updates.append({
                'variant_id': variant_id,
                'price': price,
                'compare_at_price': compare_at_price
            })

            details.append({
                'product_title': product_title,
                'variant_title': variant_title,
                'old_price': old_price,
                'new_price': str(price),
                'compare_at_price': str(compare_at_price),
                'stone_type': stone_type
            })

            logger.info(f"  {product_title} / {variant_title} ({stone_type}): ₹{old_price} -> ₹{price}")

    return updates, details


def update_theme_diamond_settings(client: ShopifyClient, diamond_configs: Dict) -> bool:
    """Update diamond price settings in theme."""
    settings = client.get_theme_settings()
    updates = {}

    # Find matching diamond slots in theme settings
    for i in range(1, 21):
        name_key = f'diamond_{i}_name'
        price_key = f'diamond_{i}_price_per_carat'
        current_name = settings.get(name_key, '').strip().lower()

        if current_name and current_name in diamond_configs:
            updates[price_key] = diamond_configs[current_name]
            logger.info(f"  Updating {name_key} ({current_name}): {diamond_configs[current_name]}")

    if updates:
        client.update_theme_settings(updates)
        return True
    return False


def main():
    """Main entry point for diamond price update."""
    # Get configuration from environment
    shop_url = os.environ.get('SHOPIFY_SHOP_URL')
    access_token = os.environ.get('SHOPIFY_ACCESS_TOKEN')
    theme_id = os.environ.get('SHOPIFY_THEME_ID')

    # Diamond config source
    use_theme_settings = os.environ.get('USE_THEME_SETTINGS', 'true').lower() == 'true'
    manual_diamond_configs = os.environ.get('DIAMOND_CONFIGS', '')

    if not all([shop_url, access_token]):
        logger.error("Missing required environment variables: SHOPIFY_SHOP_URL, SHOPIFY_ACCESS_TOKEN")
        sys.exit(1)

    theme_id = int(theme_id) if theme_id else None

    logger.info("=" * 60)
    logger.info("DIAMOND PRICE UPDATE")
    logger.info("=" * 60)

    # Initialize client
    client = ShopifyClient(shop_url, access_token, theme_id)

    # Get current theme settings
    settings = client.get_theme_settings()
    gold_rate = float(settings.get('gold_rate', 0))
    gst_percentage = float(settings.get('gst_percentage', 3))

    logger.info(f"\nCurrent gold rate: ₹{gold_rate}/gram")
    logger.info(f"GST percentage: {gst_percentage}%")

    # Determine diamond configurations to use
    if manual_diamond_configs:
        logger.info("\nUsing manually provided diamond configurations...")
        diamond_configs = parse_diamond_configs(manual_diamond_configs)

        # Update theme settings with new diamond prices
        logger.info("\nUpdating theme diamond settings...")
        update_theme_diamond_settings(client, diamond_configs)
    else:
        logger.info("\nUsing diamond configurations from theme settings...")
        diamond_configs = client.get_diamond_configs(settings)

    if not diamond_configs:
        logger.error("No diamond configurations found or provided")
        sys.exit(1)

    logger.info(f"\nDiamond configurations ({len(diamond_configs)} types):")
    for name, price in diamond_configs.items():
        logger.info(f"  {name}: ₹{price}/carat")

    # Get all products
    logger.info("\nFetching all products...")
    all_products = client.get_all_products()
    logger.info(f"Found {len(all_products)} total products")

    # Find affected products (case-insensitive stone type matching)
    logger.info("\nFinding affected products...")
    affected_products = find_affected_products(all_products, set(diamond_configs.keys()))
    logger.info(f"Found {len(affected_products)} affected products")

    if not affected_products:
        logger.info("No products affected by diamond price changes")
        sys.exit(0)

    # Process affected products
    logger.info("\nProcessing affected products...")
    updates, details = process_products(
        client, affected_products, diamond_configs, gold_rate, gst_percentage
    )

    logger.info(f"\nTotal updates: {len(updates)} variants")

    # Apply updates
    logger.info("\nApplying price updates...")
    result = client.bulk_update_variant_prices(updates)
    logger.info(f"Price updates: {result['success_count']} succeeded, {result['failed_count']} failed")

    # Build summary
    summary = {
        'diamond_types_updated': len(diamond_configs),
        'diamond_configurations': ', '.join([f"{k}: ₹{v}" for k, v in list(diamond_configs.items())[:5]]) + ('...' if len(diamond_configs) > 5 else ''),
        'gold_rate_used': f"₹{gold_rate}/gram",
        'total_products_in_store': len(all_products),
        'affected_products': len(affected_products),
        'variants_updated_success': result['success_count'],
        'variants_updated_failed': result['failed_count']
    }

    # Send email notification
    logger.info("\nSending email notification...")
    notifier = EmailNotifier()
    notifier.send_report(
        subject=f"[Shopify] Diamond Price Update - {datetime.now().strftime('%Y-%m-%d')}",
        workflow_type="Diamond Price Update",
        summary=summary,
        details=details,
        errors=result.get('errors') if result.get('errors') else None
    )

    logger.info("\n" + "=" * 60)
    logger.info("DIAMOND PRICE UPDATE COMPLETE")
    logger.info("=" * 60)

    if result['failed_count'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
