import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client
import openai
import time

# Load environment variables
load_dotenv()

# Initialize Supabase client directly
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# Initialize OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")


def generate_display_name(product_name: str, description: str = "") -> str:
    """
    Generate a clean, short display name from Amazon's SEO-filled product name
    """

    prompt = f"""You are a product naming expert. Convert this Amazon product name into a clean, retail-ready display name.

Amazon Product Name: {product_name}

Rules:
1. Maximum 6 words
2. Keep the core product type and key feature
3. Remove SEO filler, marketing hype, and brand names (unless it's a well-known brand like Apple, Nike, etc.)
4. Keep important specs (size, capacity, material) if relevant
5. Make it sound natural, not robotic
6. Capitalize like a proper product title

Examples:
- "Insulated Stainless Steel Water Bottle, 32oz, Leak Proof, BPA Free, Hot & Cold, Double Wall Vacuum..." → "32oz Insulated Water Bottle"
- "Premium Wireless Bluetooth Headphones with Noise Cancelling, 30 Hour Battery, Comfortable Over-Ear..." → "Noise Cancelling Wireless Headphones"
- "Personalized Custom Engraved Photo Frame, Wooden Picture Frame, Holds 4x6 Photos, Perfect Gift..." → "Personalized Wooden Photo Frame"

Return ONLY the clean display name, nothing else."""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=20
        )

        display_name = response.choices[0].message.content.strip()

        # Remove quotes if present
        display_name = display_name.strip('"').strip("'")

        # Limit to 6 words as a safety check
        words = display_name.split()
        if len(words) > 6:
            display_name = " ".join(words[:6])

        return display_name

    except Exception as e:
        print(f"❌ Error generating display name: {e}")
        # Fallback: truncate to first 6 words
        words = product_name.split()[:6]
        return " ".join(words)


def update_all_display_names():
    """Generate and update display names for all existing products"""

    # Get all products without display names
    response = supabase.table('gifts').select('id, name, description').is_('display_name', 'null').execute()
    products = response.data

    if not products:
        print("✅ All products already have display names!")
        return

    print(f"🔄 Found {len(products)} products without display names")
    print("=" * 60)

    updated = 0
    errors = 0

    for i, product in enumerate(products, 1):
        try:
            original_name = product['name']
            print(f"\n[{i}/{len(products)}]")
            print(f"  Original: {original_name[:70]}...")

            # Generate display name
            display_name = generate_display_name(
                product_name=original_name,
                description=product.get('description', '')
            )

            # Update database
            supabase.table('gifts').update({
                'display_name': display_name
            }).eq('id', product['id']).execute()

            print(f"  ✨ Display:  {display_name}")
            updated += 1

            # Rate limit to avoid hitting OpenAI too hard (2 requests/second)
            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ Error: {e}")
            errors += 1
            continue

    print("\n" + "=" * 60)
    print(f"✅ Successfully updated: {updated}")
    print(f"❌ Errors: {errors}")
    print(f"📊 Total processed: {len(products)}")


if __name__ == "__main__":
    print("🚀 Starting display name generation...")
    print(f"📍 Supabase URL: {os.getenv('SUPABASE_URL')[:30]}...")
    print(f"🔑 OpenAI Key: {os.getenv('OPENAI_API_KEY')[:20]}..." if os.getenv(
        'OPENAI_API_KEY') else "❌ OpenAI Key missing!")
    print()

    update_all_display_names()
    print("\n✨ Done!")