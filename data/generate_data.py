"""Synthetic Data Generator for Phoenix Shopper Assistant.

Generates realistic e-commerce products, shoppers, and past orders.
Saves to data/catalogue.json and data/shoppers.json.
"""

import json
import os
import random

PRODUCTS = [
    # Electronics - Laptops & Tablets
    {
        "product_id": "ELEC-LAP-001",
        "title": "Apple MacBook Air M3 15-inch",
        "description": "Supercharged by Apple M3 chip with an 8-core CPU and 10-core GPU. Liquid Retina display, all-day battery life up to 18 hours, silent fanless design.",
        "category": "Electronics",
        "brand": "Apple",
        "price": 134900.0,
        "currency": "INR",
        "stock_quantity": 25,
        "rating": 4.8,
        "specs": {"ram_gb": 16, "storage_gb": 512, "screen_inch": 15.3, "color": "Midnight", "weight_kg": 1.51},
        "tags": ["laptop", "apple", "macbook", "m3", "ultrabook", "macos", "premium"],
        "multilingual_titles": {"hi": "एप्पल मैकबुक एयर एम3", "hinglish": "Apple Macbook Air M3 15 inch badiya laptop"}
    },
    {
        "product_id": "ELEC-LAP-002",
        "title": "Dell XPS 13 Plus Laptop",
        "description": "Intel Core i7 13th Gen with capacitive touch function row, zero-lattice keyboard, and seamless glass touchpad with 4K OLED display.",
        "category": "Electronics",
        "brand": "Dell",
        "price": 149990.0,
        "currency": "INR",
        "stock_quantity": 12,
        "rating": 4.6,
        "specs": {"ram_gb": 16, "storage_gb": 1024, "screen_inch": 13.4, "color": "Platinum", "weight_kg": 1.26},
        "tags": ["laptop", "dell", "xps", "windows", "touchscreen", "oled"],
        "multilingual_titles": {"hi": "डेल एक्सपीएस 13 प्लस", "hinglish": "Dell XPS 13 Plus high performance laptop"}
    },
    {
        "product_id": "ELEC-LAP-003",
        "title": "Lenovo IdeaPad Slim 3",
        "description": "Budget-friendly everyday laptop powered by AMD Ryzen 5 processor, 15.6-inch FHD anti-glare screen, rapid charge technology.",
        "category": "Electronics",
        "brand": "Lenovo",
        "price": 42990.0,
        "currency": "INR",
        "stock_quantity": 40,
        "rating": 4.2,
        "specs": {"ram_gb": 8, "storage_gb": 512, "screen_inch": 15.6, "color": "Arctic Grey", "weight_kg": 1.62},
        "tags": ["laptop", "lenovo", "budget", "affordable", "student", "amd"],
        "multilingual_titles": {"hi": "लेनोवो आइडियापैड स्लिम 3", "hinglish": "Lenovo sasta budget laptop under 50000"}
    },
    {
        "product_id": "ELEC-LAP-004",
        "title": "HP Pavilion 15 Gaming Laptop",
        "description": "Equipped with Intel Core i5 and NVIDIA GeForce RTX 3050. 144Hz refresh rate, dual-fan cooling system for intense gaming.",
        "category": "Electronics",
        "brand": "HP",
        "price": 68990.0,
        "currency": "INR",
        "stock_quantity": 18,
        "rating": 4.4,
        "specs": {"ram_gb": 16, "storage_gb": 512, "gpu": "RTX 3050", "screen_inch": 15.6, "weight_kg": 2.23},
        "tags": ["laptop", "gaming", "hp", "pavilion", "rtx", "graphics"],
        "multilingual_titles": {"hi": "एचपी पवेलियन गेमिंग लैपटॉप", "hinglish": "HP gaming laptop badhiya graphics ke sath"}
    },
    {
        "product_id": "ELEC-TAB-001",
        "title": "Apple iPad Pro 11-inch M4",
        "description": "The thinnest Apple product ever, breakthrough Ultra Retina XDR OLED display, mind-blowing M4 chip performance with Apple Pencil Pro support.",
        "category": "Electronics",
        "brand": "Apple",
        "price": 99900.0,
        "currency": "INR",
        "stock_quantity": 15,
        "rating": 4.9,
        "specs": {"ram_gb": 8, "storage_gb": 256, "screen_inch": 11.0, "color": "Space Black", "weight_kg": 0.44},
        "tags": ["tablet", "ipad", "apple", "m4", "oled", "drawing"],
        "multilingual_titles": {"hi": "एप्पल आईपैड प्रो", "hinglish": "Apple iPad Pro 11 inch tablet"}
    },

    # Electronics - Smartphones
    {
        "product_id": "ELEC-PHO-001",
        "title": "Apple iPhone 15 Pro",
        "description": "Forged in titanium with aerospace-grade strength. A17 Pro game-changing chip, Customizable Action button, 48MP main camera with 3x Telephoto.",
        "category": "Electronics",
        "brand": "Apple",
        "price": 129900.0,
        "currency": "INR",
        "stock_quantity": 30,
        "rating": 4.8,
        "specs": {"ram_gb": 8, "storage_gb": 256, "color": "Natural Titanium", "battery_mah": 3274, "camera_mp": 48},
        "tags": ["phone", "smartphone", "iphone", "apple", "5g", "titanium"],
        "multilingual_titles": {"hi": "एप्पल आईफोन 15 प्रो", "hinglish": "iPhone 15 pro behtareen camera phone"}
    },
    {
        "product_id": "ELEC-PHO-002",
        "title": "Samsung Galaxy S24 Ultra 5G",
        "description": "Galaxy AI features including Circle to Search, Live Translate, and Note Assist. Snapdragon 8 Gen 3 with 200MP camera and embedded S Pen.",
        "category": "Electronics",
        "brand": "Samsung",
        "price": 129999.0,
        "currency": "INR",
        "stock_quantity": 22,
        "rating": 4.7,
        "specs": {"ram_gb": 12, "storage_gb": 512, "color": "Titanium Gray", "battery_mah": 5000, "camera_mp": 200},
        "tags": ["phone", "smartphone", "samsung", "galaxy", "ai", "5g", "spen"],
        "multilingual_titles": {"hi": "सैमसंग गैलेक्सी एस24 अल्ट्रा", "hinglish": "Samsung Galaxy S24 Ultra top flagship phone"}
    },
    {
        "product_id": "ELEC-PHO-003",
        "title": "OnePlus 12 5G",
        "description": "Snapdragon 8 Gen 3, 4th Gen Hasselblad Camera System, 5400 mAh battery with 100W SUPERVOOC hyper-fast charging.",
        "category": "Electronics",
        "brand": "OnePlus",
        "price": 64999.0,
        "currency": "INR",
        "stock_quantity": 35,
        "rating": 4.6,
        "specs": {"ram_gb": 16, "storage_gb": 512, "color": "Flowy Emerald", "battery_mah": 5400, "charging_w": 100},
        "tags": ["phone", "oneplus", "5g", "fastcharging", "flagship"],
        "multilingual_titles": {"hi": "वनप्लस 12 5जी", "hinglish": "Oneplus 12 tez charging phone"}
    },
    {
        "product_id": "ELEC-PHO-004",
        "title": "Samsung Galaxy M14 5G",
        "description": "Affordable 5G smartphone with massive 6000 mAh battery, 50MP triple camera setup, and 12-band 5G support for high-speed connectivity.",
        "category": "Electronics",
        "brand": "Samsung",
        "price": 11990.0,
        "currency": "INR",
        "stock_quantity": 50,
        "rating": 4.1,
        "specs": {"ram_gb": 6, "storage_gb": 128, "color": "Smoky Teal", "battery_mah": 6000, "camera_mp": 50},
        "tags": ["phone", "samsung", "budget", "under 15000", "5g", "big battery"],
        "multilingual_titles": {"hi": "सैमसंग गैलेक्सी एम14", "hinglish": "Samsung ka sasta 5G phone under 15000"}
    },
    {
        "product_id": "ELEC-PHO-005",
        "title": "Google Pixel 8a",
        "description": "Google Tensor G3 chip, Best Take, Audio Magic Eraser, 7 years of OS updates, and vibrant 120Hz Actua display.",
        "category": "Electronics",
        "brand": "Google",
        "price": 52999.0,
        "currency": "INR",
        "stock_quantity": 0,  # Out of stock for testing
        "rating": 4.5,
        "specs": {"ram_gb": 8, "storage_gb": 128, "color": "Bay Blue", "camera_mp": 64},
        "tags": ["phone", "google", "pixel", "tensor", "camera", "ai"],
        "multilingual_titles": {"hi": "गूगल पिक्सल 8ए", "hinglish": "Google pixel 8a shandar camera phone"}
    },

    # Electronics - Audio & Wearables
    {
        "product_id": "ELEC-AUD-001",
        "title": "Sony WH-1000XM5 Wireless Headphones",
        "description": "Industry leading noise canceling with two processors and 8 microphones. Up to 30 hours battery life with crystal clear hands-free calling.",
        "category": "Electronics",
        "brand": "Sony",
        "price": 28990.0,
        "currency": "INR",
        "stock_quantity": 40,
        "rating": 4.7,
        "specs": {"battery_hours": 30, "color": "Silver", "anc": True, "type": "Over-Ear"},
        "tags": ["headphones", "sony", "anc", "audio", "noise cancelling", "bluetooth"],
        "multilingual_titles": {"hi": "सोनी डब्ल्यूएच-1000एक्सएम5 हेडफोन", "hinglish": "Sony noise cancelling headphones best sound"}
    },
    {
        "product_id": "ELEC-AUD-002",
        "title": "Apple AirPods Pro (2nd Gen)",
        "description": "Active Noise Cancellation reduces up to 2x more background noise. Adaptive Audio, Personalized Spatial Audio, and USB-C MagSafe case.",
        "category": "Electronics",
        "brand": "Apple",
        "price": 24900.0,
        "currency": "INR",
        "stock_quantity": 60,
        "rating": 4.8,
        "specs": {"battery_hours": 24, "anc": True, "case": "USB-C", "type": "In-Ear"},
        "tags": ["earbuds", "airpods", "apple", "anc", "spatial audio"],
        "multilingual_titles": {"hi": "एप्पल एयरपॉड्स प्रो", "hinglish": "Apple Airpods Pro 2nd gen best earbuds"}
    },
    {
        "product_id": "ELEC-AUD-003",
        "title": "boAt Rockerz 450 Bluetooth On-Ear Headphones",
        "description": "Pocket-friendly wireless headphones with 40mm dynamic drivers, padded ear cushions, up to 15 hours playback, and dual modes.",
        "category": "Electronics",
        "brand": "boAt",
        "price": 1499.0,
        "currency": "INR",
        "stock_quantity": 100,
        "rating": 4.0,
        "specs": {"battery_hours": 15, "color": "Luscious Black", "type": "On-Ear"},
        "tags": ["headphones", "boat", "budget", "under 2000", "bluetooth"],
        "multilingual_titles": {"hi": "बोट रॉकर्स 450", "hinglish": "boAt saste bluetooth headphones"}
    },

    # Footwear
    {
        "product_id": "FOOT-RUN-001",
        "title": "Nike Air Zoom Pegasus 40 Running Shoes",
        "description": "Springy ride for any run with responsive Zoom Air cushioning, breathable engineered mesh upper, and durable waffle outsole.",
        "category": "Footwear",
        "brand": "Nike",
        "price": 10495.0,
        "currency": "INR",
        "stock_quantity": 30,
        "rating": 4.6,
        "specs": {"size_uk": 9, "color": "Black/White", "gender": "Unisex", "type": "Running"},
        "tags": ["shoes", "running", "nike", "pegasus", "jogging", "marathon"],
        "multilingual_titles": {"hi": "नाइके एयर जूम पेगासस रनिंग जूते", "hinglish": "Nike running shoes marathon aur running ke liye"}
    },
    {
        "product_id": "FOOT-RUN-002",
        "title": "Adidas Ultraboost Light Running Shoes",
        "description": "Epic energy return with lightest Boost cushioning yet. Continental Natural Rubber outsole gives extraordinary traction on wet and dry surfaces.",
        "category": "Footwear",
        "brand": "Adidas",
        "price": 14999.0,
        "currency": "INR",
        "stock_quantity": 18,
        "rating": 4.7,
        "specs": {"size_uk": 8, "color": "Core Black", "gender": "Men", "type": "Running"},
        "tags": ["shoes", "adidas", "ultraboost", "running", "comfort"],
        "multilingual_titles": {"hi": "एडिडास अल्ट्राबूस्ट जूते", "hinglish": "Adidas Ultraboost running shoes sabse comfortable"}
    },
    {
        "product_id": "FOOT-CAS-001",
        "title": "Puma Smash V2 Sneakers",
        "description": "Classic tennis-inspired silhouette made from soft suede leather, cushioned SoftFoam+ sockliner, and durable rubber sole.",
        "category": "Footwear",
        "brand": "Puma",
        "price": 3299.0,
        "currency": "INR",
        "stock_quantity": 45,
        "rating": 4.3,
        "specs": {"size_uk": 8, "color": "Peacoat Navy", "material": "Suede", "type": "Casual"},
        "tags": ["shoes", "sneakers", "puma", "casual", "suede"],
        "multilingual_titles": {"hi": "प्यूमा स्मैश वी2 स्नीकर्स", "hinglish": "Puma casual sneakers roz pehanne ke liye"}
    },

    # Apparel
    {
        "product_id": "APP-MEN-001",
        "title": "Levi's 511 Slim Fit Jeans",
        "description": "Modern slim jeans with room to move. Crafted from premium stretch denim with signature 5-pocket styling and leather patch.",
        "category": "Apparel",
        "brand": "Levi's",
        "price": 2899.0,
        "currency": "INR",
        "stock_quantity": 55,
        "rating": 4.4,
        "specs": {"waist_inch": 32, "fit": "Slim Fit", "color": "Dark Indigo", "material": "99% Cotton 1% Elastane"},
        "tags": ["jeans", "denim", "levis", "pants", "men"],
        "multilingual_titles": {"hi": "लीवाइस 511 स्लिम फिट जींस", "hinglish": "Levis slim fit badiya jeans"}
    },
    {
        "product_id": "APP-WOM-001",
        "title": "Kanjivaram Pure Soft Silk Saree",
        "description": "Exquisite traditional handloom pure silk saree with opulent golden zari border and rich pallu. Comes with unstitched matching blouse piece.",
        "category": "Apparel",
        "brand": "CraftVilla",
        "price": 7999.0,
        "currency": "INR",
        "stock_quantity": 20,
        "rating": 4.7,
        "specs": {"fabric": "Pure Silk", "color": "Royal Maroon & Gold", "length_m": 6.3, "occasion": "Wedding/Festive"},
        "tags": ["saree", "silk", "kanjivaram", "traditional", "wedding", "ethnic"],
        "multilingual_titles": {"hi": "कांचीवरम शुद्ध रेशमी साड़ी", "hinglish": "Kanjivaram pure silk saree shaadi ke liye"}
    },

    # Home & Kitchen
    {
        "product_id": "HOME-KIT-001",
        "title": "Philips Digital Air Fryer HD9252",
        "description": "Rapid Air Technology cooks delicious food with up to 90% less fat. Touch screen with 7 preset cooking programs and keep warm mode.",
        "category": "Home & Kitchen",
        "brand": "Philips",
        "price": 8499.0,
        "currency": "INR",
        "stock_quantity": 35,
        "rating": 4.5,
        "specs": {"capacity_l": 4.1, "power_w": 1400, "color": "Black", "type": "Air Fryer"},
        "tags": ["air fryer", "philips", "kitchen", "cooking", "healthy", "fryer"],
        "multilingual_titles": {"hi": "फिलिप्स डिजिटल एयर फ्रायर", "hinglish": "Philips air fryer kam tel me cooking"}
    },
    {
        "product_id": "HOME-VAC-001",
        "title": "Ecovacs Deebot N8 Pro Robot Vacuum Cleaner",
        "description": "2-in-1 sweeping and mopping with TrueMapping LiDAR navigation, 3D obstacle avoidance, 2600Pa suction power, and app control.",
        "category": "Home & Kitchen",
        "brand": "Ecovacs",
        "price": 27999.0,
        "currency": "INR",
        "stock_quantity": 14,
        "rating": 4.4,
        "specs": {"suction_pa": 2600, "battery_mah": 3200, "navigation": "LiDAR", "type": "Robot Vacuum"},
        "tags": ["vacuum", "robot vacuum", "cleaner", "mop", "smart home"],
        "multilingual_titles": {"hi": "इकोवैक्स रोबोट वैक्यूम क्लीनर", "hinglish": "Ghar ki safai ke liye robot vacuum cleaner"}
    },

    # Groceries
    {
        "product_id": "GROC-TEA-001",
        "title": "Organic India Tulsi Green Tea Classic (100g)",
        "description": "Certified organic antioxidant rich green tea blended with nourishing Tulsi herbs. Enhances immunity and boosts stamina.",
        "category": "Groceries",
        "brand": "Organic India",
        "price": 280.0,
        "currency": "INR",
        "stock_quantity": 150,
        "rating": 4.6,
        "specs": {"weight_g": 100, "organic": True, "form": "Loose Leaves"},
        "tags": ["tea", "green tea", "tulsi", "organic", "health", "ayurveda"],
        "multilingual_titles": {"hi": "ऑर्गेनिक इंडिया तुलसी ग्रीन टी", "hinglish": "Tulsi green tea health ke liye"}
    }
]

SHOPPERS = [
    {
        "customer_id": "C001",
        "name": "Rahul Sharma",
        "email": "rahul.sharma@example.com",
        "loyalty_tier": "Platinum",
        "address": "42 Indiranagar, Bengaluru, KA 560038"
    },
    {
        "customer_id": "C002",
        "name": "Priya Patel",
        "email": "priya.patel@example.com",
        "loyalty_tier": "Gold",
        "address": "15 CG Road, Ahmedabad, GJ 380009"
    },
    {
        "customer_id": "C003",
        "name": "Amit Verma",
        "email": "amit.verma@example.com",
        "loyalty_tier": "Silver",
        "address": "78 Gomti Nagar, Lucknow, UP 226010"
    },
    {
        "customer_id": "C004",
        "name": "Sneha Roy",
        "email": "sneha.roy@example.com",
        "loyalty_tier": "Bronze",
        "address": "12 Salt Lake, Kolkata, WB 700091"
    },
    {
        "customer_id": "C005",
        "name": "Vikram Rao",
        "email": "vikram.rao@example.com",
        "loyalty_tier": "Platinum",
        "address": "89 Jubilee Hills, Hyderabad, TS 500033"
    }
]

ORDERS = [
    {
        "order_id": "ORD-9021",
        "customer_id": "C001",
        "product_id": "ELEC-LAP-001",
        "quantity": 1,
        "total_amount": 134900.0,
        "order_status": "Delivered",
        "order_date": "2026-11-10",
        "tracking_number": "TRK-BLR-88192"
    },
    {
        "order_id": "ORD-9022",
        "customer_id": "C001",
        "product_id": "ELEC-AUD-002",
        "quantity": 1,
        "total_amount": 24900.0,
        "order_status": "Shipped",
        "order_date": "2026-11-19",
        "tracking_number": "TRK-DEL-44102"
    },
    {
        "order_id": "ORD-8411",
        "customer_id": "C002",
        "product_id": "FOOT-RUN-001",
        "quantity": 1,
        "total_amount": 10495.0,
        "order_status": "Delivered",
        "order_date": "2026-11-05",
        "tracking_number": "TRK-AMD-11928"
    },
    {
        "order_id": "ORD-8412",
        "customer_id": "C002",
        "product_id": "HOME-KIT-001",
        "quantity": 1,
        "total_amount": 8499.0,
        "order_status": "Processing",
        "order_date": "2026-11-20",
        "tracking_number": "TRK-MUM-77312"
    },
    {
        "order_id": "ORD-7301",
        "customer_id": "C003",
        "product_id": "ELEC-PHO-004",
        "quantity": 1,
        "total_amount": 11990.0,
        "order_status": "Delivered",
        "order_date": "2026-10-25",
        "tracking_number": "TRK-LKO-99302"
    },
    {
        "order_id": "ORD-6101",
        "customer_id": "C004",
        "product_id": "APP-WOM-001",
        "quantity": 1,
        "total_amount": 7999.0,
        "order_status": "Delivered",
        "order_date": "2026-10-15",
        "tracking_number": "TRK-CCU-55201"
    },
    {
        "order_id": "ORD-5201",
        "customer_id": "C005",
        "product_id": "ELEC-PHO-002",
        "quantity": 1,
        "total_amount": 129999.0,
        "order_status": "Delivered",
        "order_date": "2026-11-01",
        "tracking_number": "TRK-HYD-66190"
    }
]


def generate():
    os.makedirs(os.path.dirname(__file__), exist_ok=True)
    cat_path = os.path.join(os.path.dirname(__file__), "catalogue.json")
    shop_path = os.path.join(os.path.dirname(__file__), "shoppers.json")

    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(PRODUCTS, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(PRODUCTS)} products -> {cat_path}")

    shoppers_data = {
        "shoppers": SHOPPERS,
        "orders": ORDERS
    }
    with open(shop_path, "w", encoding="utf-8") as f:
        json.dump(shoppers_data, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(SHOPPERS)} shoppers and {len(ORDERS)} orders -> {shop_path}")


if __name__ == "__main__":
    generate()
