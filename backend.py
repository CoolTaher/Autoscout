"""
backend.py — Autoscout backend

Structure:
    1. Config / constants
    2. Query parsing (city extraction)
    3. Bright Data: trigger + fetch (unified for test and live mode)
    4. Response parsing (JSON / NDJSON / dead_page detection)
    5. Normalization
    6. Ranking + insights

TEST_MODE lives here, not in app.py — flip TEST_MODE and set
TEST_COLLECTION_ID below, and get_car_listings() transparently uses
whichever source is active. Nothing downstream (parsing, normalizing,
ranking) differs between the two modes — they converge on the same
fetch_dataset() call.

DEBUG is a temporary flag: while True, functions return extra detail
in the status string (e.g. exact failure reason, raw response snippet)
so app.py can display it during development. Set to False once the
pipeline is confirmed stable — status strings become short and clean
again ("poll_failed" instead of "poll_failed: empty body, code=200").
"""

import os
import json
import re
import time
import statistics

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
load_dotenv()


# =======================================================================
# 1. Config / constants
# =======================================================================

BRIGHTDATA_TOKEN = os.getenv("BRIGHTDATA_API_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

COLLECTOR_ID = "c_mt08rawd1kysv6q7l5"
TRIGGER_URL = "https://api.brightdata.com/dca/trigger"
DATASET_URL = "https://api.brightdata.com/dca/dataset"

FALLBACK_CITIES = [
"Mumbai","Kolkata","Delhi","Chennai","Bangalore","Ahmedabad","Pune","Hyderabad","Surat","Prayagraj","Kanpur","Kanpur","Belahi","Vadodara","Nadampalaiyam","Lucknow","Kannankulam","Mahuakheraganj","Nagla","Jaipur","Kottarassheri","Attadappa","Barmhan Kalan","Gorakhpur","Nagpur",
"Guwahati","Ghaziabad","Coimbatore","Patna","Rajkot","Vishakhapatnam","Indore","Abhepur","Gumanwala","Thane","Bhopal","Agra","Peyanvilai","Pimpri-Chinchwad","Harbatpur","Saundhonwali","Ludhiana","Meerut","Madurai","Nasik","Faridabad","Madarpur","Najafgarh","Jabalpur","Madanpur",
"Kamalwaganja Gaur","Kalyan","Asansol","Vijayawada","Vasai-Virar","Varanasi","Kalleli","Srinagar","Aurangabad","Dhanbad","Amritsar","Haora","Ranchi","Gwalior","Jodhpur","Chandigarh","Raipur","Warangal","Kota","Bareilly","Solapur","Hubli","Mysore","Trichinopoly","Moradabad",
"Tiruppur","Jamnagar","Gurgaon","Aligarh","Jalandhar","Bhubaneshwar","Bhayandar","Narela","Shishgarh","Thiruvananthapuram","Dispur","Durgapur","Bhiwandi","Saharanpur","Shiliguri","Avadi","Salem","Jui","Amaldu","Kimsar","Sinduri","Kochi","Gorakhpur","Guntur","Karaikandi",
"Bhavnagar","Noida","Bhangar","Jamshedpur","Bhilai","Mangalore","Chitai","Khatyari","Dhaulra","Bihta","Calicut","Cuttack","Salimpur","Tumkur","Pandharpur","Dehra Dun","Malegaon","Premnagar","Lachhman Garhi","Tiparpur","Bokaro Steel City","Kolhapur","Nava Raipur","Raurkela","Morbi",
"Morbi","Ajmer","Nanded","Amravati","Nellore","Gulbarga","Bikaner","Agartala","Chandrapur","Surappattu","Loni","Ujjain","Orai","Jhansi","Ulhasnagar","Jammu","Tuticorin","Purnea","Muzaffarnagar","Karimnagar","Belgaum","Vellore","Dewal Thal","Jamtola","Bardoli",
"Gaya","Ambattur","Junagadh","Jalgaon","Chhatarpur","Kurnool","Udaipur","Mathura","Sangli","Davangere","Mothihari","Akola","Bettiah","Shorapur","Tinnevelly","Bellary","Bhagalpur","Patiala","Salt Lake City","Etawa","Quilon","Mulangodi","Munro Turuttu","Karur","Muzaffarnagar",
"Bairia","Bhatpara","Sirur","Kakinada","Panihati","Dhulia","Rohtak","Maler Kotla","Bilaspur","Korba","Kolga","Bhilwara","Sikar","Sasaram","Brahmapur","Ahmadnagar","Shahjanpur","Khanapur","Cuddapah","Kovilpatti","Rajahmundry","Alwar","Sambalpur","Muzaffarpur","Kamarhati",
"Barkot","Campiernagar","Bijapur","Ratnagiri","Rampur","Shimoga","Barh","Hapur","Pattikad","Trichur","Barddhaman","Kulti","Panvel","Nizamabad","Parbhani","Hisar","Oulgaret","Ingraj Bazar","Yelahanka","Bihar","Darbhanga","Idar","Sikandarabad","Panipat","Sibsagar",
"Aizawl","Bali","Ghandinagar","Farrukhabad","Surajgarha","Nagercoil","Dewas","Sonpur","Chunchura","Ichalkaranji","Tirupati","Karnal","Bhatinda","Jalna","Satna","Mau","Barasat","Sonipat","Saugor","Ratlam","Handwara","Drug","Imphal","Anantapur","Ranipet"
]

# --- Test mode switch --- Testing Enviroment for
# While True: get_car_listings() skips triggering a new scrape and
# reuses TEST_COLLECTION_ID instead. Set to False for real, live scrapes.
TEST_MODE = False
TEST_COLLECTION_ID = "j_mt4av3xn1atd5aq0pc"

# --- Debug switch ---
# While True: status strings carry extra diagnostic detail.
DEBUG = True


# =======================================================================
# 2. Query parsing — city extraction
# =======================================================================

def parse_query(query):
    """Extract city from the query. Regex first, Gemini as fallback."""

    if not query or not query.strip():
        return {}, "none"

    # First: fast local matching
    regex_result = extract_with_regex(query)

    if regex_result:
        return regex_result, "regex"

    # Second: Gemini only if regex fails
    gemini_result = extract_with_gemini(query)

    if gemini_result is not None:
        return gemini_result, "gemini"

    return {}, "none"


def extract_with_gemini(query: str) -> dict | None:
    """Use Gemini as a fast fallback to extract a city name from a query.

    Returns:
        {"city": "<name>"} if a city was found
        {}                 if Gemini explicitly found no city
        None               if Gemini is unavailable or the call failed
    """
    if not GEMINI_API_KEY:
        return None

    prompt = f"""Identify the city in this user query (direct mention, nickname, or famous characteristic).

        Return ONLY the city name, nothing else. No punctuation, no state/country, no explanation.
        If no city can be identified, return exactly: NONE

        Examples:
        Query: Show me cars in Pune -> Pune
        Query: Find used cars around Mumbai -> Mumbai
        Query: Show me cars in the City of Lakes -> Udaipur
        Query: I want a car in the Pink City -> Jaipur
        Query: Show me some used cars -> NONE

        Query: {query}
        Answer:"""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=15000))

        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",  # check ai.google.dev/gemini-api/docs/pricing for current free-tier models
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=10,
            ),
        )

        text = (response.text or "").strip().strip("`")

        if not text or text.upper() == "NONE":
            return {} if text else None

        return {"city": text.lower()}

    except Exception as e:
        if DEBUG:
            print("Gemini error:", e)
        return None

def extract_with_regex(query):
    """Substring match against FALLBACK_CITIES. Never fails."""
    query = query.lower()
    for city in FALLBACK_CITIES:
        pattern = r"\b" + re.escape(city.lower()) + r"\b"
        if re.search(pattern, query):
            return {"city": city.lower()}
    return {}


# =======================================================================
# 3. Bright Data: trigger + fetch (unified for test and live mode)
# =======================================================================

def slugify(text):
    """Lowercases, trims, and converts spaces to hyphens for URL segments."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def build_cars24_url(city):
    """Maps a city name to its Cars24 listings page URL."""
    slug = slugify(city)
    return f"https://www.cars24.com/buy-used-cars-{slug}/"


def build_custom_url(city, budget):
    """
    Builds a Cars24 budget-filtered URL.

    Example:
        city="Pune", budget=10
        -> https://www.cars24.com/buy-used-cars-under-10-lakhs-pune/

    Both city and budget are required.
    """

    if city is None or budget is None:
        return None

    city = str(city).strip()

    if not city:
        return None

    try:
        budget = float(budget)
    except (TypeError, ValueError):
        return None

    if budget <= 0:
        return None

    # Keep integer budgets clean: 10 instead of 10.0
    if budget.is_integer():
        budget_text = str(int(budget))
    else:
        budget_text = str(budget)

    city_slug = slugify(city)

    return (
        f"https://www.cars24.com/"
        f"buy-used-cars-under-{budget_text}-lakhs-{city_slug}/"
    )


def build_filter_url(city, value):
    """
    Builds a rigid, fully custom Cars24 URL from a free-text filter
    segment and a city — both required.

    Example:
        city="pune", value="tata-nexon-cars-under-10-lakhs"
        -> https://www.cars24.com/buy-used-tata-nexon-cars-under-10-lakhs-pune/

    Returns None if either input is missing/empty.
    """
    return build_custom_url(city, value)


def trigger_scrape(city=None, target_url=None):
    """
    Triggers a new scrape job. Pass either `city` (builds the standard
    city listings URL) or `target_url` directly (e.g. from
    build_custom_url()) — target_url takes precedence if both are given.

    Returns (collection_id, status). collection_id is None on failure.
    """
    # ---------------------------------------------------------------
    # NEVER allow an empty search to reach Bright Data
    # ---------------------------------------------------------------
    if target_url is None and city is None:
        return None, "invalid_search"

    if target_url is not None:
        target_url = str(target_url).strip()

        if not target_url:
            return None, "invalid_search"

    if city is not None:
        city = str(city).strip()

        if not city:
            return None, "invalid_search"

    if not BRIGHTDATA_TOKEN:
        return None, "no_token"

    headers = {
        "Authorization": f"Bearer {BRIGHTDATA_TOKEN}",
        "Content-Type": "application/json",
    }
    params = {"collector": COLLECTOR_ID, "queue_next": "1"}
    url = target_url or build_cars24_url(city)
    payload = [{"url": url}]

    try:
        response = requests.post(TRIGGER_URL, headers=headers, params=params, json=payload)
        response.raise_for_status()
        collection_id = response.json()["collection_id"]
        return collection_id, "triggered"
    
    except Exception as e:
        detail = f"trigger_failed: {e}" if DEBUG else "trigger_failed"

        return None, detail


def fetch_dataset(collection_id, max_attempts=15, poll_interval=15):
    """
    Poll Bright Data until the job finishes.

    Returns:
        (raw_text, "fetched")      -> 200 response with data
        (None, "job_failed")       -> job finished but failed
        (None, "empty_result")     -> job finished successfully with no data
        (None, "timeout")          -> max polling attempts reached
        (None, "error")            -> unexpected request/API error
        (None, "no_token")         -> missing Bright Data token
    """

    if not BRIGHTDATA_TOKEN:
        return None, "no_token"

    headers = {
        "Authorization": f"Bearer {BRIGHTDATA_TOKEN}"
    }

    log_url = f"https://api.brightdata.com/dca/log/{collection_id}"

    for attempt in range(max_attempts):

        try:
            response = requests.get(
                DATASET_URL,
                headers=headers,
                params={"id": collection_id},
                timeout=30,
            )
        except requests.RequestException as e:
            if DEBUG:
                print("Bright Data dataset error:", e)
            return None, "error"

        # -----------------------------------------------------------
        # 202 = job is still running
        # -----------------------------------------------------------
        if response.status_code == 202:
            if DEBUG:
                print(
                    f"Bright Data job still running "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )

            time.sleep(poll_interval)
            continue

        # -----------------------------------------------------------
        # 200 = dataset endpoint responded
        # -----------------------------------------------------------
        if response.status_code == 200:

            raw_text = response.text.strip()

            # -------------------------------------------------------
            # 200 + data
            # Parse it later in parse_response()
            # -------------------------------------------------------
            if raw_text:
                return raw_text, "fetched"

            # -------------------------------------------------------
            # 200 + EMPTY
            #
            # Dataset has no body. Now check the actual job log.
            # -------------------------------------------------------
            try:
                log_response = requests.get(
                    log_url,
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as e:
                if DEBUG:
                    print("Bright Data log error:", e)

                time.sleep(poll_interval)
                continue

            if log_response.status_code != 200:
                if DEBUG:
                    print(
                        "Bright Data log returned:",
                        log_response.status_code
                    )

                time.sleep(poll_interval)
                continue

            try:
                metadata = log_response.json()
            except ValueError:
                if DEBUG:
                    print("Bright Data log returned invalid JSON")

                time.sleep(poll_interval)
                continue

            job_status = metadata.get("status")

            if DEBUG:
                print("Bright Data job metadata:", metadata)

            # -------------------------------------------------------
            # Job has definitely finished
            # -------------------------------------------------------
            if job_status == "done":

                # Job failed
                if metadata.get("fails", 0) > 0:
                    return None, "job_failed"

                # Job completed but produced nothing
                if metadata.get("lines", 0) == 0:
                    return None, "empty_result"

                # Something inconsistent:
                # job says done and has lines, but dataset body is empty.
                return None, "error"

            # -------------------------------------------------------
            # Job isn't done yet.
            # Keep polling.
            # -------------------------------------------------------
            time.sleep(poll_interval)
            continue

        # -----------------------------------------------------------
        # Unexpected HTTP response
        # -----------------------------------------------------------
        if DEBUG:
            print(
                "Unexpected Bright Data response:",
                response.status_code,
                response.text[:300]
            )

        return None, "error"

    # ---------------------------------------------------------------
    # Maximum polling attempts reached
    # ---------------------------------------------------------------
    return None, "timeout"


def get_car_listings(city=None, target_url=None):
    """
    Main entry point used by app.py. Returns (raw_data, status).

    Pass `city` for a standard city-wide search, or `target_url` for a
    custom-filtered search (from build_custom_url()) — target_url takes
    precedence if both are given.

    In TEST_MODE, reuses TEST_COLLECTION_ID instead of triggering a
    real scrape. In live mode, triggers a new scrape first. Either way,
    both paths converge on fetch_dataset() + parse_response(), so
    downstream behavior (error handling, dead-page detection, parsing)
    is identical regardless of mode.
    """
    if TEST_MODE:
        collection_id = TEST_COLLECTION_ID
    else:
        collection_id, status = trigger_scrape(city=city, target_url=target_url)
        if not collection_id:
            return None, status
        time.sleep(5)  # brief buffer before first poll

    raw_text, status = fetch_dataset(collection_id)
    if raw_text is None:
        return None, status

    return parse_response(raw_text)


# =======================================================================
# 4. Response parsing (JSON / NDJSON / dead_page detection)
# =======================================================================

def parse_response(raw_text):
    """
    Parse Bright Data response.

    Returns:
        (raw_data, "success")
        (None, "job_failed")
        (None, "empty_result")
        (None, "error")
    """

    if not raw_text or not raw_text.strip():
        return None, "error"

    # ---------------------------------------------------------------
    # Try normal JSON first
    # ---------------------------------------------------------------
    try:
        raw_data = json.loads(raw_text)

    except json.JSONDecodeError:

        # -----------------------------------------------------------
        # Try NDJSON
        # -----------------------------------------------------------
        try:
            raw_data = [
                json.loads(line)
                for line in raw_text.splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError:
            return None, "error"

    # ---------------------------------------------------------------
    # Cars24 dead page
    # ---------------------------------------------------------------
    def _is_dead_page(item):
        return (
            isinstance(item, dict)
            and item.get("error_code") == "dead_page"
        )

    if _is_dead_page(raw_data):
        return None, "job_failed"

    if (
        isinstance(raw_data, list)
        and len(raw_data) == 1
        and _is_dead_page(raw_data[0])
    ):
        return None, "job_failed"

    # ---------------------------------------------------------------
    # Valid response but no listings
    # ---------------------------------------------------------------
    if isinstance(raw_data, list) and not raw_data:
        return None, "empty_result"

    # ---------------------------------------------------------------
    # Valid listings
    # ---------------------------------------------------------------
    if isinstance(raw_data, list):
        return raw_data, "success"

    # ---------------------------------------------------------------
    # Unexpected JSON structure
    # ---------------------------------------------------------------
    return None, "error"

# =======================================================================
# 5. Normalization
# =======================================================================

def parse_price_to_number(price_str):
    """Converts '₹7.74 lakh' -> 774000.0, etc."""
    if not price_str:
        return None
    text = price_str.lower().replace("₹", "").strip()

    match = re.search(r"([\d.]+)\s*lakh", text)
    if match:
        return float(match.group(1)) * 100_000

    match = re.search(r"([\d.]+)\s*crore", text)
    if match:
        return float(match.group(1)) * 10_000_000

    digits = re.sub(r"[^\d.]", "", text)
    return float(digits) if digits else None


def parse_km_to_number(km_str):
    """Converts '47,319 km' -> 47319."""
    if not km_str:
        return None
    digits = re.sub(r"[^\d]", "", km_str)
    return int(digits) if digits else None


def normalize_listings(raw_data):
    """Converts raw Bright Data output into a clean, common shape."""
    listings = []
    for item in raw_data:
        listings.append({
            "car_name": item.get("car_name"),
            "year": item.get("year"),
            "variant": item.get("variant"),
            "price_text": item.get("price"),
            "price_value": parse_price_to_number(item.get("price")),
            "km_text": item.get("km_driven"),
            "km_value": parse_km_to_number(item.get("km_driven")),
            "fuel": item.get("fuel"),
            "transmission": item.get("transmission"),
            "address": item.get("car_address"),
            "location": item.get("location"),
            "verified_dealer": item.get("verified_dealer"),
            "listing_url": item.get("listing_url"),
        })
    return listings


# =======================================================================
# 6. Ranking + insights
# =======================================================================

def rank_listings(listings):
    """
    Ranks cars by a combined value score: 60% recency (newer = better),
    40% price (cheaper = better). Highest score first.
    """
    valid_years = [int(l["year"]) for l in listings if str(l.get("year", "")).isdigit()]
    valid_prices = [l["price_value"] for l in listings if l.get("price_value")]

    min_year, max_year = (min(valid_years), max(valid_years)) if valid_years else (None, None)
    min_price, max_price = (min(valid_prices), max(valid_prices)) if valid_prices else (None, None)

    for listing in listings:
        year = int(listing["year"]) if str(listing.get("year", "")).isdigit() else None
        price = listing.get("price_value")

        if year and max_year != min_year:
            year_score = (year - min_year) / (max_year - min_year)
        else:
            year_score = 0.5

        if price and max_price != min_price:
            price_score = (max_price - price) / (max_price - min_price)
        else:
            price_score = 0.5

        listing["value_score"] = (year_score * 0.60) + (price_score * 0.40)

    listings.sort(key=lambda l: l.get("value_score", 0), reverse=True)
    return listings

def add_insight_badges(listings):
    """
    Adds a per-listing insight badge: a green 'X% below median' tag for
    cars priced meaningfully under the median, or an amber 'low km for
    age' tag for cars with unusually low mileage for their year.
    Stored as listing['insight_badge'] = (text, tone) or None.
    """
    prices = [l["price_value"] for l in listings if l.get("price_value")]
    median_price = statistics.median(prices) if prices else None

    for listing in listings:
        price = listing.get("price_value")
        year = int(listing["year"]) if str(listing.get("year", "")).isdigit() else None
        km = listing.get("km_value")

        badge = None

        if median_price and price and price < median_price * 0.92:
            pct = round((1 - price / median_price) * 100)
            badge = (f"{pct}% below median", "positive")
        elif year and km:
            expected_km = max(2026 - year, 1) * 12000
            if km < expected_km * 0.6:
                badge = ("low km for age", "caution")

        listing["insight_badge"] = badge

    return listings

def search_summary(listings):
    """Match count, median price, average km — for summary display."""
    prices = [l["price_value"] for l in listings if l["price_value"]]
    kms = [l["km_value"] for l in listings if l["km_value"]]
    return {
        "count": len(listings),
        "median_price": statistics.median(prices) if prices else None,
        "avg_km": int(statistics.mean(kms)) if kms else None,
    }