import streamlit as st
from pathlib import Path
import base64
import html

import backend


# ==========================================================
# PAGE SETUP
# ==========================================================

st.set_page_config(
    page_title="Autoscout",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ==========================================================
# LOAD CSS
# ==========================================================

CSS_FILE = Path(__file__).parent / "style.css"

with open(CSS_FILE, "r", encoding="utf-8") as f:
    CUSTOM_CSS = f.read()

st.html(f"""
<style>
{CUSTOM_CSS}
</style>
""")


# ==========================================================
# BACKGROUND IMAGE
# ==========================================================

CAR_IMAGE = Path(__file__).parent / "car_image.jpg"

if CAR_IMAGE.exists():
    import base64

    image_data = base64.b64encode(CAR_IMAGE.read_bytes()).decode()

    st.markdown(
        f"""
        <div class="car-background"
             style="background-image: url('data:image/jpeg;base64,{image_data}');">
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==========================================================
# SESSION STATE
# ==========================================================

if "results" not in st.session_state:
    st.session_state.results = None

if "search_message" not in st.session_state:
    st.session_state.search_message = None

if "last_searched_query" not in st.session_state:
    st.session_state.last_searched_query = ""

if "use_custom_filter" not in st.session_state:
    st.session_state.use_custom_filter = False

# ==========================================================
# TITLE
# ==========================================================

st.html("""
<div class="autoscout-brand">

    <div class="autoscout-logo">
        AUTOSCOUT
    </div>

    <div class="autoscout-tagline">
        Find the right car. Without the noise.
    </div>

</div>
""")

# ==========================================================
# MAIN SEARCH INPUT
# ==========================================================

search_col, button_col = st.columns(
    [5.5, 1.2],
    gap="small"
)

with search_col:

    query = st.text_input(
        "Natural search",
        placeholder="e.g. automatic Swift under 6 lakh in Pune",
        label_visibility="collapsed",
        key="natural_search",
        disabled=st.session_state.get("use_custom_filter", False),
    )


with button_col:

    search_clicked = st.button(
        "Find cars",
        use_container_width=True,
        type="primary",
        disabled=st.session_state.get("use_custom_filter", False),
    )


# ==========================================================
# CUSTOM FILTER
# ==========================================================

use_custom_filter = st.toggle(
    "🎯 Custom Filter Mode — Search your car on with your exact budget",
    key="use_custom_filter",
)

custom_search_clicked = False
custom_city, custom_value = "", ""

if use_custom_filter:

    with st.container(border=True):

        filter_city_col, filter_value_col, filter_button_col = st.columns([2, 2.5, 1.2])

        with filter_city_col:
            custom_city = st.text_input("📍 City *", placeholder="Any one city e.g: Pune, Mumbai, Delhi etc", key="custom_filter_city")

        with filter_value_col:
            custom_value = st.text_input(
                "💰 Under lakhs *", placeholder="Whole digits e.g: 10, 15, 25", key="custom_filter_value"
            )

        custom_url_preview = backend.build_filter_url(custom_city, custom_value)

        with filter_button_col:
            st.write("")
            custom_search_clicked = st.button(
                "🚗 Search",
                use_container_width=True,
                type="primary",
                disabled=custom_url_preview is None,
                key="custom_filter_search",
            )

        custom_url_preview = backend.build_filter_url(
            custom_city,
            custom_value
        )


# ==========================================================
# SEARCH FUNCTION
# ==========================================================

def run_search(user_query):

    filters, method = backend.parse_query(
        user_query
    )

    city = filters.get("city")

    if not city or not str(city).strip():

        return None, (
            "warning",
            "Please include a city, for example: Pune."
        )

    steps = [
        f"🔎 Connecting to Cars24 for {city}...",
        "🚗 Scrolling through listings...",
        "📊 Extracting car details...",
        "✨ Almost there...",
    ]

    with st.status(steps[0], expanded=True) as status_box:
        import threading, itertools, time as _time

        result_holder = {}

        def _run():
            result_holder["raw_data"], result_holder["status"] = backend.get_car_listings(city=city)

        thread = threading.Thread(target=_run)
        thread.start()

        for msg in itertools.cycle(steps):
            status_box.update(label=msg)
            thread.join(timeout=2.5)
            if not thread.is_alive():
                break

        thread.join()
        raw_data, status = result_holder["raw_data"], result_holder["status"]
        status_box.update(label="✅ Done", state="complete")

    if status != "success":

        if status == "job_failed":
            message = "Cars not available."

        elif status == "empty_result":
            message = "Please try popular cities for car availability."

        elif status == "no_token":
            message = "Something went wrong. Please try again."

        elif status == "timeout":
            message = "Search timed out. Please try again."

        else:
            message = "Something went wrong. Please try again."

        return None, ("error", message)

    # ------------------------------------------------------
    # NORMALIZE
    # ------------------------------------------------------

    listings = backend.normalize_listings(
        raw_data
    )

    # ------------------------------------------------------
    # RANK
    # ------------------------------------------------------

    listings = backend.rank_listings(
        listings
    )

    # ------------------------------------------------------
    # INSIGHTS
    # ------------------------------------------------------

    listings = backend.add_insight_badges(
        listings
    )

    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------

    summary = backend.search_summary(
        listings
    )

    return (listings, summary), None


# ==========================================================
# RUN SEARCH
# ==========================================================

if search_clicked and not st.session_state.use_custom_filter:

    if not query or not query.strip():

        st.session_state.results = None

        st.session_state.search_message = (
            "warning",
            "Please describe the city in which you are looking for your car."
        )

    else:

        clean_query = query.strip()

        if clean_query != st.session_state.last_searched_query:

            results, message = run_search(
                clean_query
            )

            st.session_state.results = results
            st.session_state.search_message = message
            st.session_state.last_searched_query = clean_query

            st.rerun()


elif custom_search_clicked and st.session_state.use_custom_filter:

    if not custom_city.strip() or not custom_value.strip():

        st.session_state.results = None

        st.session_state.search_message = (
            "warning",
            "Both City and Budget are required."
        )

    else:

        target_url = backend.build_filter_url(
            custom_city,
            custom_value,
        )

        with st.spinner(
            f"Finding cars in {custom_city.strip()} "
            f"under ₹{custom_value.strip()} lakh..."
        ):

            raw_data, status = backend.get_car_listings(
                target_url=target_url
            )

        if status != "success":

            if status == "job_failed":
                message = "Cars not available."

            elif status == "empty_result":
                message = "Please try a different city or budget."

            elif status == "invalid_search":
                message = "Please try a valid city and budget."

            elif status == "no_token":
                message = "Something went wrong. Please try again."

            elif status == "timeout":
                message = "Search timed out. Please try again."

            else:
                message = "Something went wrong. Please try again."

            st.session_state.results = None
            st.session_state.search_message = (
                "error",
                message,
            )

        else:

            listings = backend.normalize_listings(
                raw_data
            )

            listings = backend.rank_listings(
                listings
            )

            listings = backend.add_insight_badges(
                listings
            )

            summary = backend.search_summary(
                listings
            )

            st.session_state.results = (
                listings,
                summary,
            )

            st.session_state.search_message = None

            st.session_state.last_searched_query = (
                f"{custom_city.strip()}|{custom_value.strip()}"
            )

        st.rerun()

# ==========================================================
# SEARCH MESSAGE
# ==========================================================

if st.session_state.search_message:

    kind, message = st.session_state.search_message

    if kind == "warning":
        st.warning(message)

    elif kind == "error":
        st.error(message)

    elif kind == "info":
        st.info(message)


# ==========================================================
# RESULTS
# ==========================================================

if st.session_state.results:

    listings, summary = st.session_state.results

    if not listings:

        st.info("No cars found for this search.")

    else:

        # ==================================================
        # RESULTS HEADER
        # ==================================================

        median_price = summary.get("median_price")
        avg_km = summary.get("avg_km")
        count = summary.get("count", 0)

        if median_price:
            median_text = f"₹{median_price / 100000:.2f}L"
        else:
            median_text = "N/A"

        if avg_km:
            km_text = f"{avg_km:,} km"
        else:
            km_text = "N/A"

        # ==================================================
        # METRICS
        # ==================================================

        metric1, metric2, metric3 = st.columns(3)

        with metric1:

            st.html(f"""
            <div class="av-metric-card">

                <div class="av-metric-label">
                    TOTAL MATCHES
                </div>

                <div class="av-metric-value">
                    {count}
                </div>

                <div class="av-metric-sub">
                    cars found
                </div>

            </div>
            """)


        with metric2:

            st.html(f"""
            <div class="av-metric-card">

                <div class="av-metric-label">
                    MEDIAN PRICE
                </div>

                <div class="av-metric-value">
                    {median_text}
                </div>

                <div class="av-metric-sub">
                    median price
                </div>

            </div>
            """)


        with metric3:

            st.html(f"""
            <div class="av-metric-card">

                <div class="av-metric-label">
                    AVERAGE KM
                </div>

                <div class="av-metric-value">
                    {km_text}
                </div>

                <div class="av-metric-sub">
                    average mileage
                </div>

            </div>
            """)



        # ==================================================
        # TOP 3
        # ==================================================

        st.html("""
        <div class="section-header">
            🏆 Top matches
        </div>
        """)


        top_listings = listings[:3]


        def esc(value):
            if value is None:
                return ""

            return (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )


        for index, listing in enumerate(top_listings):

            # ----------------------------------------------
            # BASIC DETAILS
            # ----------------------------------------------

            car_name = str(
                listing.get("car_name") or "Unknown Model"
            ).strip()

            year = str(
                listing.get("year") or ""
            ).strip()

            variant = str(
                listing.get("variant")
                or "Variant not available"
            ).strip()

            # Prevent:
            # 2025 + "2025 Toyota Urban Cruiser Taisor"

            if year and car_name.startswith(year):
                title = car_name
            elif year:
                title = f"{year} {car_name}"
            else:
                title = car_name

            #Best prices
            price = str(
                listing.get("price_text")
                or "Price unavailable"
            ).strip()

            km = str(
                listing.get("km_text")
                or "N/A"
            ).strip()

            fuel = str(
                listing.get("fuel")
                or "N/A"
            ).strip()

            transmission = str(
                listing.get("transmission")
                or "N/A"
            ).strip()

            location = (
                listing.get("address")
                or listing.get("location")
                or "Location unavailable"
            )

            location = str(location).strip()

            # ----------------------------------------------
            # BEST VALUE BADGE
            # ----------------------------------------------

            best_value_html = """
            <div class="car-best-tag">
                ★ BEST VALUE
            </div>
            """

            # ----------------------------------------------
            # INSIGHT
            # ----------------------------------------------

            insight_html = ""

            insight = listing.get("insight_badge")

            if insight:

                text, tone = insight

                insight_class = (
                    "insight-positive"
                    if tone == "positive"
                    else "insight-caution"
                )

                insight_html = f"""
                <span class="insight-badge {insight_class}">
                    {esc(text)}
                </span>
                """

            # ----------------------------------------------
            # LISTING URL
            # ----------------------------------------------

            listing_url = listing.get("listing_url")

            if listing_url:

                listing_url = esc(
                    listing_url
                )

                link_html = f"""
                <a
                    class="car-link"
                    href="{listing_url}"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    View listing →
                </a>
                """

            else:

                link_html = ""

            # ----------------------------------------------
            # CARD
            # ----------------------------------------------

            st.html(f"""
            <div class="car-card">

                <div class="car-card-top">

                    <div class="car-card-main">

                        {best_value_html}

                        <div class="car-rank">
                            #{index + 1} TOP MATCH
                        </div>

                        <div class="car-title">
                            {esc(title)}
                        </div>

                        <div class="car-variant">
                            {esc(variant)}
                        </div>

                    </div>


                    <div class="car-price-section">

                        <div class="car-price">
                            {esc(price)}
                        </div>

                        {insight_html}

                    </div>

                </div>


                <div class="car-specs">

                    <span>
                        ⏱ {esc(km)}
                    </span>

                    <span>
                        ⛽ {esc(fuel)}
                    </span>

                    <span>
                        ⚙️ {esc(transmission)}
                    </span>

                </div>


                <div class="car-location">
                    📍 {esc(location)}
                </div>


                {link_html}

            </div>
            """)

        # ==================================================
        # MORE RESULTS
        # ==================================================

        if len(listings) > 3:

            st.html(f"""
            <div class="more-results-label">
                {len(listings) - 3} more cars available
            </div>
            """)

            if st.button(
                f"View all {len(listings) - 3} results ↓",
                use_container_width=True,
                key="view_all_results",
            ):

                st.session_state.show_all_results = True
                st.rerun()

        # ==================================================
        # ALL RESULTS
        # ==================================================

        if st.session_state.get("show_all_results", False):

            remaining_listings = listings[3:]


            st.html("""
            <div class="section-header">
                All results
            </div>
            """)


            for index, listing in enumerate(
                remaining_listings,
                start=4
            ):

                car_name = html.escape(
                    str(listing.get("car_name") or "Unknown Model")
                )

                year = html.escape(
                    str(listing.get("year") or "")
                )

                variant = html.escape(
                    str(listing.get("variant") or "Variant not available")
                )

                price = html.escape(
                    str(listing.get("price_text") or "Price unavailable")
                )

                km = html.escape(
                    str(listing.get("km_text") or "N/A")
                )

                fuel = html.escape(
                    str(listing.get("fuel") or "N/A")
                )

                transmission = html.escape(
                    str(listing.get("transmission") or "N/A")
                )

                location = (
                    listing.get("address")
                    or listing.get("location")
                    or "Location unavailable"
                )

                location = html.escape(str(location))

                listing_url = listing.get("listing_url")

                st.html(f"""
                <div class="car-card">

                    <div class="car-card-top">

                        <div class="car-card-main">

                            <div class="car-rank">
                                #{index}
                            </div>

                            <div class="car-title">
                                {car_name}
                            </div>

                            <div class="car-variant">
                                {variant}
                            </div>

                        </div>


                        <div class="car-price">
                            {price}
                        </div>

                    </div>


                    <div class="car-specs">

                        <span>⏱ {km}</span>
                        <span>⛽ {fuel}</span>
                        <span>⚙️ {transmission}</span>

                    </div>


                    <div class="car-location">
                        📍 {location}
                    </div>

                    <div class="car-card-footer">
                        {link_html}
                    </div>

                </div>
                """)