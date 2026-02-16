# Shopify Price Updater

Automated price management for Shopify stores with gold, silver, and diamond products.

## Features

- **Automatic Price Updates**: Fetches live gold/silver prices from goldapi.io and updates all products
- **Manual Price Updates**: Enter prices manually, include/exclude specific products by handle
- **Diamond Price Updates**: Update diamond prices and recalculate all affected products
- **Email Notifications**: Detailed reports sent on completion
- **Efficient Bulk Operations**: Uses Shopify GraphQL API for fast updates

## Setup

### 1. Repository Secrets

Configure the following secrets in your GitHub repository:

#### Required Shopify Secrets
| Secret | Description |
|--------|-------------|
| `SHOPIFY_SHOP_URL` | Your Shopify store URL (e.g., `mystore.myshopify.com`) |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API access token |
| `SHOPIFY_THEME_ID` | Theme ID to update settings (optional, uses main theme if not set) |

#### Required API Secrets
| Secret | Description |
|--------|-------------|
| `GOLDAPI_KEY` | API key from [goldapi.io](https://www.goldapi.io/) for live metal prices |

#### Email Notification Secrets (Optional)
| Secret | Description |
|--------|-------------|
| `SMTP_HOST` | SMTP server host (default: `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP server port (default: `587`) |
| `SMTP_USER` | SMTP username/email |
| `SMTP_PASSWORD` | SMTP password or app password |
| `FROM_EMAIL` | Sender email address |
| `TO_EMAILS` | Comma-separated recipient emails |

### 2. goldapi.io Setup

1. Sign up at [goldapi.io](https://www.goldapi.io/)
2. Get your API key from the dashboard
3. Add it as `GOLDAPI_KEY` secret

### 3. Email Setup (Gmail Example)

1. Enable 2-factor authentication on your Google account
2. Generate an App Password: Google Account > Security > App Passwords
3. Use your email as `SMTP_USER` and the app password as `SMTP_PASSWORD`

## Workflows

### 1. Automatic Price Update

**Trigger**: Scheduled daily at 9:00 AM IST (or manual trigger)

- Fetches live gold (24K) and silver prices from goldapi.io in INR
- Updates theme settings with new rates
- Recalculates all product prices
- Updates `jhango.gold_rate` or `jhango.silver_rate` metafields on products
- Sends email report on completion

**Price Formula (Gold)**:
```
Metal Price = Weight × Purity Factor × Gold Rate
Stone Price = Stone Carats × Price Per Carat (from theme diamond settings)
Making Charge = Metal Price × Making %
Discount = Making Charge × Discount %
Subtotal = Metal + Stone + Making - Discount + Hallmarking + Certification
GST = Subtotal × 3%
Total = Subtotal + GST
Compare At Price = Total / 0.80 (shows 20% off)
```

**Price Formula (Silver)**:
```
Silver Price = Weight × 1000
Diamond Price = Lab Diamond Carats × 40000
Total = Silver Price + Diamond Price
Compare At Price = Total / 0.80 (shows 20% off)
```

### 2. Manual Price Update

**Trigger**: Manual dispatch only

**Inputs**:
- `gold_rate`: Gold rate per gram (24K) in INR
- `silver_rate`: Silver rate per gram in INR
- `include_handles`: Product handles to include (comma or newline separated)
- `exclude_handles`: Product handles to exclude (takes precedence over include)

**Behavior**:
- If `include_handles` is empty, updates all products (minus excludes)
- If all products are being updated, also updates theme settings
- If subset is selected, only updates product prices and metafields

### 3. Diamond Price Update

**Trigger**: Manual dispatch only

**Inputs**:
- `use_theme_settings`: Use diamond prices from theme settings (default: true)
- `diamond_configs`: Manual diamond configurations

**Diamond Config Formats**:
```json
{"natural diamond": 50000, "lab grown": 15000}
```
or
```
natural diamond:50000,lab grown:15000
```

**Behavior**:
- Finds all products with matching stone types (case-insensitive)
- Recalculates prices using current gold rate from theme
- Updates theme diamond settings if manual configs provided

## Project Structure

```
shopify-price-updater/
├── .github/
│   └── workflows/
│       ├── auto-price-update.yml
│       ├── manual-price-update.yml
│       └── diamond-price-update.yml
├── scripts/
│   ├── price_calculator.py      # Price calculation logic
│   ├── shopify_client.py        # Shopify API client
│   ├── email_notifier.py        # Email notification utility
│   ├── auto_price_update.py     # Automatic update script
│   ├── manual_price_update.py   # Manual update script
│   └── diamond_price_update.py  # Diamond update script
├── requirements.txt
└── README.md
```

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export SHOPIFY_SHOP_URL="mystore.myshopify.com"
export SHOPIFY_ACCESS_TOKEN="your-token"
export GOLDAPI_KEY="your-goldapi-key"

# Run automatic update
cd scripts
python auto_price_update.py

# Run manual update
export GOLD_RATE="7500"
export INCLUDE_HANDLES="product-1,product-2"
python manual_price_update.py
```

## Metafields Used

### Product Metafields (Read)
| Namespace | Key | Description |
|-----------|-----|-------------|
| `custom` | `metal_weight` | Metal weight in grams |
| `custom` | `stone_carats` | Total stone carats |
| `custom` | `stone_types` | Comma-separated stone types |
| `custom` | `stone_prices_per_carat` | Fallback price per carat |
| `custom` | `making_charge_percentage` | Making charge % |
| `custom` | `discount_making_charge` | Discount % on making |
| `jhango` | `hallmarking` | Hallmarking charge |
| `jhango` | `certification` | Certification charge |

### Product Metafields (Written)
| Namespace | Key | Description |
|-----------|-----|-------------|
| `jhango` | `gold_rate` | Current gold rate (for gold products) |
| `jhango` | `silver_rate` | Current silver rate (for silver products) |

## Theme Settings Used

| Setting | Description |
|---------|-------------|
| `gold_rate` | Gold rate per gram (24K) |
| `silver_rate` | Silver rate per gram |
| `gst_percentage` | GST percentage (default: 3) |
| `diamond_1_name` to `diamond_20_name` | Diamond type names |
| `diamond_1_price_per_carat` to `diamond_20_price_per_carat` | Diamond prices |
