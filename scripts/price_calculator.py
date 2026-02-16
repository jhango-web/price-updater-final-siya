#!/usr/bin/env python3
"""
Price Calculator Module
=======================
Shared price calculation logic for gold and silver products.
"""

import math
from typing import Dict, List, Tuple, Optional


class GoldPriceCalculator:
    """Calculate prices for gold products."""

    PURITY_FACTORS = {
        '24KT': 1.000, '24K': 1.000,
        '22KT': 0.916, '22K': 0.916,
        '18KT': 0.750, '18K': 0.750,
        '14KT': 0.585, '14K': 0.585,
        '10KT': 0.417, '10K': 0.417,
        '9KT': 0.375, '9K': 0.375,
    }

    def __init__(self, gold_rate: float, gst_percentage: float = 3.0, diamond_configs: Dict = None):
        self.gold_rate = gold_rate
        self.gst_percentage = gst_percentage
        self.diamond_configs = diamond_configs or {}

    def get_purity_factor(self, purity_value: str) -> float:
        """Get purity factor from option value like '9KT', '14KT', etc."""
        purity_upper = purity_value.upper().strip()
        return self.PURITY_FACTORS.get(purity_upper, 1.0)

    def get_stone_price_per_carat(self, stone_type: str, fallback_price: float = 0) -> float:
        """Get stone price per carat from diamond configurations."""
        if stone_type:
            stone_type_lower = stone_type.lower().strip()
            if stone_type_lower in self.diamond_configs:
                return self.diamond_configs[stone_type_lower]
            # Try partial match
            for key, price in self.diamond_configs.items():
                if stone_type_lower in key or key in stone_type_lower:
                    return price
        return fallback_price

    def calculate(
        self,
        metal_weight: float,
        purity_value: str,
        stone_carats: float,
        stone_type: str,
        stone_price_per_carat: float,
        making_charge_percentage: float,
        hallmarking_charge: float,
        certification_charge: float,
        discount_making_charge: float = 0
    ) -> Tuple[float, float, Dict]:
        """
        Calculate the final price for a gold product variant.

        Returns:
            Tuple of (price, compare_at_price, breakdown_dict)
        """
        purity_factor = self.get_purity_factor(purity_value)

        # Metal Price
        metal_price = math.ceil(metal_weight * purity_factor * self.gold_rate)

        # Stone Price
        price_per_carat = self.get_stone_price_per_carat(stone_type, stone_price_per_carat)
        stone_price = math.ceil(stone_carats * price_per_carat) if stone_carats else 0

        # Making Charge
        making_charge = math.ceil(metal_price * (making_charge_percentage / 100))

        # Discount
        discount = math.ceil(making_charge * (discount_making_charge / 100))

        # Hallmarking and Certification
        hallmarking_rounded = math.ceil(hallmarking_charge)
        certification_rounded = math.ceil(certification_charge)

        # Subtotal
        subtotal = metal_price + stone_price + making_charge - discount + hallmarking_rounded + certification_rounded

        # GST
        gst = math.ceil(subtotal * (self.gst_percentage / 100))

        # Total
        total = subtotal + gst

        # Compare At Price (price shows 20% off from compare_at)
        compare_at_price = math.ceil(total / 0.80)

        breakdown = {
            'metal_weight': metal_weight,
            'purity': purity_value,
            'purity_factor': purity_factor,
            'gold_rate': self.gold_rate,
            'metal_price': metal_price,
            'stone_carats': stone_carats,
            'stone_type': stone_type,
            'stone_price_per_carat': price_per_carat,
            'stone_price': stone_price,
            'making_charge': making_charge,
            'making_charge_percentage': making_charge_percentage,
            'discount': discount,
            'discount_percentage': discount_making_charge,
            'hallmarking_charge': hallmarking_rounded,
            'certification_charge': certification_rounded,
            'subtotal': subtotal,
            'gst': gst,
            'gst_percentage': self.gst_percentage,
            'total': total,
            'compare_at_price': compare_at_price
        }

        return total, compare_at_price, breakdown


class SilverPriceCalculator:
    """Calculate prices for silver products."""

    SILVER_WEIGHT_MULTIPLIER = 1000
    LAB_DIAMOND_PRICE_PER_CARAT = 40000

    def __init__(self, silver_rate: float = None):
        # Silver rate is stored for reference but not used in calculation
        self.silver_rate = silver_rate

    def calculate(self, silver_weight: float, lab_diamond_carats: float) -> Tuple[float, float, Dict]:
        """
        Calculate the final price for a silver product.

        Formula: (Silver Weight × 1000) + (Lab Diamond Carats × 40,000)

        Returns:
            Tuple of (price, compare_at_price, breakdown_dict)
        """
        silver_price = math.ceil(silver_weight * self.SILVER_WEIGHT_MULTIPLIER)
        diamond_price = math.ceil(lab_diamond_carats * self.LAB_DIAMOND_PRICE_PER_CARAT)

        total = silver_price + diamond_price
        compare_at_price = math.ceil(total / 0.80)

        breakdown = {
            'silver_weight': silver_weight,
            'silver_multiplier': self.SILVER_WEIGHT_MULTIPLIER,
            'silver_price': silver_price,
            'lab_diamond_carats': lab_diamond_carats,
            'lab_diamond_price_per_carat': self.LAB_DIAMOND_PRICE_PER_CARAT,
            'diamond_price': diamond_price,
            'total': total,
            'compare_at_price': compare_at_price
        }

        return total, compare_at_price, breakdown
