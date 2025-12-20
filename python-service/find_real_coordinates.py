"""
Find REAL Element Coordinates using Playwright
Connects to Chrome via CDP and gets exact bounding box of elements.

Usage:
1. Chrome must be running with: --remote-debugging-port=9222
2. Navigate to booking.com manually
3. Run: python find_real_coordinates.py
"""

import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed!")
    print("   Run: pip install playwright")
    print("   Then: playwright install chromium")
    sys.exit(1)

def get_element_coordinates(page, selector: str, description: str) -> dict:
    """Get exact coordinates of an element"""
    try:
        element = page.wait_for_selector(selector, timeout=3000)
        if element:
            box = element.bounding_box()
            if box:
                center_x = int(box['x'] + box['width'] / 2)
                center_y = int(box['y'] + box['height'] / 2)

                return {
                    'found': True,
                    'description': description,
                    'selector': selector,
                    'bounding_box': {
                        'x': int(box['x']),
                        'y': int(box['y']),
                        'width': int(box['width']),
                        'height': int(box['height'])
                    },
                    'center': {
                        'x': center_x,
                        'y': center_y
                    }
                }
    except Exception as e:
        pass

    return {
        'found': False,
        'description': description,
        'selector': selector,
        'error': 'Element not found'
    }


def main():
    print("=" * 60)
    print("  PLAYWRIGHT COORDINATE FINDER")
    print("  Finding REAL element coordinates from DOM")
    print("=" * 60)
    print()

    # Get screen info
    try:
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        print(f"📺 Screen Resolution: {screen_w} x {screen_h}")
    except:
        screen_w, screen_h = 1920, 1200
        print(f"📺 Screen Resolution: {screen_w} x {screen_h} (assumed)")

    print()
    print("🔌 Connecting to Chrome via CDP...")
    print("   (Chrome must be running with --remote-debugging-port=9222)")
    print()

    try:
        with sync_playwright() as p:
            # Connect to existing Chrome
            browser = p.chromium.connect_over_cdp('http://localhost:9222')

            # FIX: contexts is a property, not a method
            contexts = browser.contexts
            if not contexts:
                print("❌ No browser contexts found!")
                return

            context = contexts[0]

            # FIX: pages is a property, not a method
            pages = context.pages
            if not pages:
                print("❌ No pages found!")
                return

            page = pages[0]

            # Get current URL
            current_url = page.url
            print(f"📄 Current Page: {current_url}")
            print()

            # Check if it's Booking.com
            if 'booking.com' not in current_url.lower():
                print("⚠️  WARNING: Not on Booking.com!")
                print("   Navigate to booking.com first for accurate results")
                print()

            # Define selectors to search for
            selectors = [
                ('input[name="ss"]', 'Booking.com destination field (name=ss)'),
                ('input[placeholder*="Where"]', 'Input with "Where" placeholder'),
                ('input[data-testid*="destination"]', 'Destination test ID'),
                ('[data-testid="destination-container"] input', 'Destination container input'),
                ('input[type="search"]', 'Generic search input'),
                ('.sb-searchbox__input input', 'Searchbox input'),
                ('#ss', 'Element with ID "ss"'),
            ]

            print("🔍 Searching for destination field...")
            print("-" * 60)

            found_elements = []

            for selector, description in selectors:
                result = get_element_coordinates(page, selector, description)

                if result['found']:
                    found_elements.append(result)
                    box = result['bounding_box']
                    center = result['center']

                    print(f"\n✅ FOUND: {description}")
                    print(f"   Selector: {selector}")
                    print(f"   ┌─────────────────────────────────────────┐")
                    print(f"   │ Bounding Box:                          │")
                    print(f"   │   Top-Left:  ({box['x']}, {box['y']})")
                    print(f"   │   Size:      {box['width']} x {box['height']} px")
                    print(f"   │   Center:    ({center['x']}, {center['y']})")
                    print(f"   ├─────────────────────────────────────────┤")
                    print(f"   │ As Percentage of Screen:               │")
                    print(f"   │   X: {center['x']/screen_w*100:.1f}% from left")
                    print(f"   │   Y: {center['y']/screen_h*100:.1f}% from top")
                    print(f"   └─────────────────────────────────────────┘")

            if not found_elements:
                print("\n❌ No destination field found!")
                print("   Make sure you're on the Booking.com homepage")
                print()

                # Try to find ANY input fields
                print("🔍 Looking for any input fields on page...")
                inputs = page.query_selector_all('input')
                print(f"   Found {len(inputs)} input elements")

                for i, inp in enumerate(inputs[:5]):
                    try:
                        box = inp.bounding_box()
                        if box and box['width'] > 50:
                            print(f"\n   Input #{i+1}:")
                            print(f"     Position: ({int(box['x'])}, {int(box['y'])})")
                            print(f"     Size: {int(box['width'])} x {int(box['height'])}")

                            name = inp.get_attribute('name') or ''
                            placeholder = inp.get_attribute('placeholder') or ''
                            if name:
                                print(f"     name='{name}'")
                            if placeholder:
                                print(f"     placeholder='{placeholder}'")
                    except:
                        pass

            else:
                # Summary
                print("\n" + "=" * 60)
                print("  SUMMARY - REAL COORDINATES")
                print("=" * 60)

                best = found_elements[0]
                center = best['center']

                print(f"\n🎯 Best match: {best['description']}")
                print(f"\n   CLICK HERE: ({center['x']}, {center['y']})")
                print(f"   Percentage:  X={center['x']/screen_w*100:.1f}%, Y={center['y']/screen_h*100:.1f}%")

                print(f"\n📊 Compare with LUX coordinates:")
                print(f"   LUX sends:   (242, 601)")
                print(f"   Should be:   ({center['x']}, {center['y']})")
                print(f"   X error:     {242 - center['x']:+d} px")
                print(f"   Y error:     {601 - center['y']:+d} px (before scaling)")

                # Calculate what Y should be in LUX reference (1080)
                y_in_lux_ref = int(center['y'] * 1080 / screen_h)
                print(f"\n   Y in LUX reference (1080p): {y_in_lux_ref}")
                print(f"   Y error in LUX ref:         {601 - y_in_lux_ref:+d} px")

            browser.close()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Is Chrome running with --remote-debugging-port=9222?")
        print("  2. Run: playwright install chromium")
        print("  3. Check if another process is using port 9222")


if __name__ == "__main__":
    main()
