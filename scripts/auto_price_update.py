#!/usr/bin/env python3
"""
Automatic Price Update Script
=============================
Fetches gold and silver prices from goldapi.io and updates all products.
Updates theme settings and recalculates all product prices.
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime
from typing import Dict, List, Tuple, Optional

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


def fetch_gold_price(api_key: str) -> Optional[float]:
    """Fetch pure gold price per gram in INR from goldapi.io."""
    try:
        url = "https://www.goldapi.io/api/XAU/INR"
        headers = {
            "x-access-token": api_key,
            "Content-Type": "application/json"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        # price_gram_24k is the pure gold price per gram
        price = data.get('price_gram_24k')
        logger.info(f"Fetched gold price: ₹{price}/gram (24K)")
        return float(price)
    except Exception as e:
        logger.error(f"Failed to fetch gold price: {str(e)}")
        return None


def fetch_silver_price(api_key: str) -> Optional[float]:
    """Fetch pure silver price per gram in INR from goldapi.io."""
    try:
        url = "https://www.goldapi.io/api/XAG/INR"
        headers = {
            "x-access-token": api_key,
            "Content-Type": "application/json"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        # price_gram is the silver price per gram
        price = data.get('price_gram')
        logger.info(f"Fetched silver price: ₹{price}/gram")
        return float(price)
    except Exception as e:
        logger.error(f"Failed to fetch silver price: {str(e)}")
        return None


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
            # Handle JSON array values
            if value.startswith('['):
                parsed = json.loads(value)
                if parsed:
                    return float(parsed[0]) if isinstance(parsed[0], (int, float, str)) else default
            return float(value)
        except (ValueError, json.JSONDecodeError):
            return default
    return float(value) if value else default


def process_gold_products(
    client: ShopifyClient,
    products: List[Dict],
    gold_rate: float,
    diamond_configs: Dict,
    gst_percentage: float
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Process gold products and calculate new prices."""
    calculator = GoldPriceCalculator(gold_rate, gst_percentage, diamond_configs)
    updates = []
    details = []
    metafield_updates = []

    for product in products:
        if not is_gold_product(product):
            continue

        product_id = product['id']
        product_title = product['title']

        # Get product metafields
        metafields = {
            f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
            for mf in product.get('metafields', {}).get('edges', [])
        }

        # Product-level values
        making_charge_percentage = get_metafield_value(metafields, 'custom.making_charge_percentage', 0)
        discount_percentage = get_metafield_value(metafields, 'custom.discount_making_charge', 0)
        hallmarking = get_metafield_value(metafields, 'jhango.hallmarking', 0)
        certification = get_metafield_value(metafields, 'jhango.certification', 0)
        product_stone_carats = get_metafield_value(metafields, 'custom.stone_carats', 0)
        product_stone_type = metafields.get('custom.stone_types', '')
        product_stone_price = get_metafield_value(metafields, 'custom.stone_prices_per_carat', 0)
        product_metal_weight = get_metafield_value(metafields, 'custom.metal_weight', 0)

        # Update gold_rate metafield on product
        metafield_updates.append({
            'product_id': product_id,
            'namespace': 'jhango',
            'key': 'gold_rate',
            'value': str(gold_rate),
            'value_type': 'number_decimal'
        })

        # Process each variant
        for variant_edge in product.get('variants', {}).get('edges', []):
            variant = variant_edge['node']
            variant_id = variant['id']
            variant_title = variant.get('title', '')
            old_price = variant.get('price', '0')

            # Get variant metafields
            variant_metafields = {
                f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
                for mf in variant.get('metafields', {}).get('edges', [])
            }

            # Use variant-level overrides or product-level values
            metal_weight = get_metafield_value(variant_metafields, 'custom.metal_weight', product_metal_weight)
            stone_carats = get_metafield_value(variant_metafields, 'custom.stone_carats', product_stone_carats)
            stone_type = variant_metafields.get('custom.stone_types', product_stone_type)
            stone_price = get_metafield_value(variant_metafields, 'custom.stone_prices_per_carat', product_stone_price)

            # Calculate new price
            price, compare_at_price, breakdown = calculator.calculate(
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
                'compare_at_price': str(compare_at_price)
            })

            logger.info(f"  {product_title} / {variant_title}: ₹{old_price} -> ₹{price} (compare: ₹{compare_at_price})")

    return updates, details, metafield_updates


def process_silver_products(
    client: ShopifyClient,
    products: List[Dict],
    silver_rate: float
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Process silver products and calculate new prices."""
    calculator = SilverPriceCalculator(silver_rate)
    updates = []
    details = []
    metafield_updates = []

    for product in products:
        if not is_silver_product(product):
            continue

        product_id = product['id']
        product_title = product['title']

        # Get product metafields
        metafields = {
            f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
            for mf in product.get('metafields', {}).get('edges', [])
        }

        product_metal_weight = get_metafield_value(metafields, 'custom.metal_weight', 0)
        product_stone_carats = get_metafield_value(metafields, 'custom.stone_carats', 0)

        # Update silver_rate metafield on product
        metafield_updates.append({
            'product_id': product_id,
            'namespace': 'jhango',
            'key': 'silver_rate',
            'value': str(silver_rate),
            'value_type': 'number_decimal'
        })

        # Process each variant
        for variant_edge in product.get('variants', {}).get('edges', []):
            variant = variant_edge['node']
            variant_id = variant['id']
            variant_title = variant.get('title', '')
            old_price = variant.get('price', '0')

            # Get variant metafields
            variant_metafields = {
                f"{mf['node']['namespace']}.{mf['node']['key']}": mf['node']['value']
                for mf in variant.get('metafields', {}).get('edges', [])
            }

            metal_weight = get_metafield_value(variant_metafields, 'custom.metal_weight', product_metal_weight)
            stone_carats = get_metafield_value(variant_metafields, 'custom.stone_carats', product_stone_carats)

            price, compare_at_price, breakdown = calculator.calculate(metal_weight, stone_carats)

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
                'compare_at_price': str(compare_at_price)
            })

            logger.info(f"  {product_title} / {variant_title}: ₹{old_price} -> ₹{price} (compare: ₹{compare_at_price})")

    return updates, details, metafield_updates


def main():
    """Main entry point for automatic price update."""
    # Get configuration from environment
    shop_url = os.environ.get('SHOPIFY_SHOP_URL')
    access_token = os.environ.get('SHOPIFY_ACCESS_TOKEN')
    theme_id = os.environ.get('SHOPIFY_THEME_ID')
    goldapi_key = os.environ.get('GOLDAPI_KEY')

    if not all([shop_url, access_token, goldapi_key]):
        logger.error("Missing required environment variables: SHOPIFY_SHOP_URL, SHOPIFY_ACCESS_TOKEN, GOLDAPI_KEY")
        sys.exit(1)

    theme_id = int(theme_id) if theme_id else None

    logger.info("=" * 60)
    logger.info("AUTOMATIC PRICE UPDATE")
    logger.info("=" * 60)

    # Fetch live prices from goldapi.io
    logger.info("\nFetching live prices from goldapi.io...")
    gold_rate = fetch_gold_price(goldapi_key)
    silver_rate = fetch_silver_price(goldapi_key)

    if gold_rate is None or silver_rate is None:
        logger.error("Failed to fetch metal prices, aborting")
        sys.exit(1)

    logger.info(f"\nPrices fetched:")
    logger.info(f"  Gold (24K): ₹{gold_rate}/gram")
    logger.info(f"  Silver: ₹{silver_rate}/gram")

    # Initialize Shopify client
    client = ShopifyClient(shop_url, access_token, theme_id)

    # Update theme settings
    logger.info("\nUpdating theme settings...")
    client.update_theme_settings({
        'gold_rate': gold_rate,
        'silver_rate': silver_rate
    })
    logger.info("Theme settings updated")

    # Get diamond configurations from theme
    settings = client.get_theme_settings()
    diamond_configs = client.get_diamond_configs(settings)
    gst_percentage = float(settings.get('gst_percentage', 3))

    logger.info(f"\nDiamond configurations loaded: {len(diamond_configs)} types")
    logger.info(f"GST percentage: {gst_percentage}%")

    # Fetch all products
    logger.info("\nFetching all products...")
    all_products = client.get_all_products()
    logger.info(f"Found {len(all_products)} products")

    # Process gold products
    logger.info("\n--- Processing Gold Products ---")
    gold_updates, gold_details, gold_metafield_updates = process_gold_products(
        client, all_products, gold_rate, diamond_configs, gst_percentage
    )

    # Process silver products
    logger.info("\n--- Processing Silver Products ---")
    silver_updates, silver_details, silver_metafield_updates = process_silver_products(
        client, all_products, silver_rate
    )

    # Combine updates
    all_updates = gold_updates + silver_updates
    all_details = gold_details + silver_details
    all_metafield_updates = gold_metafield_updates + silver_metafield_updates

    logger.info(f"\nTotal updates to apply: {len(all_updates)} variants, {len(all_metafield_updates)} metafields")

    # Apply price updates
    logger.info("\nApplying price updates...")
    price_result = client.bulk_update_variant_prices(all_updates)
    logger.info(f"Price updates: {price_result['success_count']} succeeded, {price_result['failed_count']} failed")

    # Apply metafield updates
    logger.info("\nApplying metafield updates...")
    metafield_result = client.bulk_update_product_metafields(all_metafield_updates)
    logger.info(f"Metafield updates: {metafield_result['success_count']} succeeded, {metafield_result['failed_count']} failed")

    # Build summary
    summary = {
        'gold_rate': f"₹{gold_rate}/gram",
        'silver_rate': f"₹{silver_rate}/gram",
        'total_products': len(all_products),
        'gold_variants_updated': len(gold_updates),
        'silver_variants_updated': len(silver_updates),
        'price_updates_success': price_result['success_count'],
        'price_updates_failed': price_result['failed_count'],
        'metafield_updates_success': metafield_result['success_count'],
        'metafield_updates_failed': metafield_result['failed_count']
    }

    # Send email notification
    logger.info("\nSending email notification...")
    notifier = EmailNotifier()
    all_errors = price_result.get('errors', []) + metafield_result.get('errors', [])
    notifier.send_report(
        subject=f"[Shopify] Automatic Price Update - {datetime.now().strftime('%Y-%m-%d')}",
        workflow_type="Automatic Price Update (goldapi.io)",
        summary=summary,
        details=all_details,
        errors=all_errors if all_errors else None
    )

    logger.info("\n" + "=" * 60)
    logger.info("AUTOMATIC PRICE UPDATE COMPLETE")
    logger.info("=" * 60)

    # Exit with error code if there were failures
    if price_result['failed_count'] > 0 or metafield_result['failed_count'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
