import streamlit as st
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from playwright.async_api import async_playwright
import pandas as pd
import os

# Tell the cloud server to install the hidden browser
os.system("playwright install chromium")

# --- CORE LOGIC ---
async def get_spotify_streams_playwright(artist_id):
    url = f"https://open.spotify.com/artist/{artist_id}"
    tracks = []
    cities_data = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Remove login walls and cookie banners
            await page.evaluate("""
                document.querySelectorAll('[data-testid="login-button"], [id^="onetrust"], .GenericModal').forEach(el => el.remove());
            """)
            await page.wait_for_timeout(3000)
            
            # 1. SCRAPE THE TRACKS
            try:
                button = page.locator('button:has-text("See more")')
                if await button.count() > 0:
                    await button.first.click(force=True)
                    await page.wait_for_timeout(1000)
                else:
                    button2 = page.locator('button:has-text("Show more")')
                    if await button2.count() > 0:
                        await button2.first.click(force=True)
                        await page.wait_for_timeout(1000)
            except Exception:
                pass 
            
            rows = await page.query_selector_all('[data-testid="tracklist-row"]')
            for row in rows[:10]:
                text = await row.inner_text()
                parts = [p.strip() for p in text.split('\n') if p.strip()]
                if len(parts) >= 2:
                    streams_str = "Unknown"
                    track_name = "Unknown"
                    for p in reversed(parts):
                        if ':' in p and len(p) <= 5: continue
                        if sum(c.isdigit() for c in p) >= 1 and not any(c.isalpha() for c in p):
                            streams_str = p
                            break
                    for p in parts:
                        if any(c.isalpha() for c in p) and p != 'E':
                            track_name = p
                            break
                    tracks.append({'name': track_name, 'streams': streams_str})
                    
            # 2. SCRAPE "WHERE PEOPLE LISTEN" — Robust multi-strategy approach
            try:
                # Scroll slowly to load lazy content
                for i in range(1, 12):
                    await page.evaluate(f"window.scrollTo(0, {i * 600})")
                    await page.wait_for_timeout(400)

                # Give dynamic content time to render
                await page.wait_for_timeout(2000)

                # --- Strategy A: look for the dedicated "Where People Listen" section ---
                # Spotify renders this as a section with city name + listener count spans
                city_els = await page.query_selector_all('[data-testid="artist-top-cities"] li, [class*="TopCities"] li, [class*="top-cities"] li')
                if city_els:
                    for el in city_els[:5]:
                        text = await el.inner_text()
                        lines = [l.strip() for l in text.split('\n') if l.strip()]
                        if len(lines) >= 2:
                            cities_data.append({"City": lines[0], "Listeners": lines[1]})

                # --- Strategy B: scan all text for "Where people listen" heading ---
                if not cities_data:
                    full_text = await page.inner_text('body')
                    if "Where people listen" in full_text:
                        section = full_text.split("Where people listen")[1]
                        lines = [l.strip() for l in section.split('\n') if l.strip()]
                        i = 0
                        while i < len(lines) and len(cities_data) < 5:
                            line = lines[i]
                            # Look for a listener count line: digits + optional commas + "listeners"
                            if "listener" in line.lower() and "monthly" not in line.lower():
                                city_candidate = lines[i - 1] if i > 0 else ""
                                listeners_val = line.lower().replace("listeners", "").replace(",", "").strip()
                                if (city_candidate
                                        and not city_candidate[0].isdigit()
                                        and "Where people" not in city_candidate
                                        and len(city_candidate) < 60):
                                    if not any(c["City"] == city_candidate for c in cities_data):
                                        cities_data.append({"City": city_candidate, "Listeners": listeners_val})
                            i += 1

                # --- Strategy C: Try clicking "About" section to open a modal ---
                if not cities_data:
                    about_btn = page.locator('button:has-text("About"), [data-testid="about-section-button"], section[data-testid="about"] button')
                    if await about_btn.count() > 0:
                        await about_btn.first.click(force=True)
                        await page.wait_for_timeout(3000)

                        dialog = page.locator('[role="dialog"]')
                        if await dialog.count() > 0:
                            modal_text = await dialog.first.inner_text()
                        else:
                            modal_text = await page.inner_text('body')

                        if "Where people listen" in modal_text:
                            section = modal_text.split("Where people listen")[1]
                            lines = [l.strip() for l in section.split('\n') if l.strip()]
                            i = 0
                            while i < len(lines) and len(cities_data) < 5:
                                line = lines[i]
                                if "listener" in line.lower() and "monthly" not in line.lower():
                                    city_candidate = lines[i - 1] if i > 0 else ""
                                    listeners_val = line.lower().replace("listeners", "").replace(",", "").strip()
                                    if (city_candidate
                                            and not city_candidate[0].isdigit()
                                            and "Where people" not in city_candidate
                                            and len(city_candidate) < 60):
                                        if not any(c["City"] == city_candidate for c in cities_data):
                                            cities_data.append({"City": city_candidate, "Listeners": listeners_val})
                                i += 1

            except Exception:
                pass

        except Exception:
            pass
        finally:
            await browser.close()
            
    return tracks, cities_data

def get_release_date_from_spotify(sp, artist_name, track_name):
    clean_track_name = track_name.split('(')[0].split('-')[0].strip()
    query = f"{artist_name} {clean_track_name}"
    try:
        result = sp.search(q=query, type='track', limit=1)
        tracks = result.get('tracks', {}).get('items', [])
        if tracks:
            return tracks[0]['album']['release_date']
        return "Unknown"
    except Exception:
        return "Unknown"

async def perform_search(artist_input):
    CLIENT_ID = "1d7660677d5b4567b86bfa2d730eacd7"
    CLIENT_SECRET = "37a4d9cd968e43ad851074944d2df8e7"
    
    auth_manager = SpotifyClientCredentials(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    if "spotify.com" in artist_input or "spotify:artist:" in artist_input:
        artist_id = artist_input.split("artist/")[1].split("?")[0] if "artist/" in artist_input else artist_input.split(":")[-1]
        artist_data = sp.artist(artist_id)
        artist_name = artist_data['name']
    else:
        result = sp.search(q='artist:' + artist_input, type='artist', limit=1)
        items = result['artists']['items']
        if not items:
            return None, None, f"Artist '{artist_input}' not found."
        artist_data = items[0]
        artist_name = artist_data['name']
        artist_id = artist_data['id']

    top_tracks_data, cities_data = await get_spotify_streams_playwright(artist_id)
    if not top_tracks_data:
        return None, None, "Failed to pull track data from the Spotify web page."

    final_results = []
    for idx, track_info in enumerate(top_tracks_data, start=1):
        track_name = track_info['name']
        rel_date = get_release_date_from_spotify(sp, artist_name, track_name)
        final_results.append({
            "Rank": idx,
            "Track Name": track_name,
            "Release Date": rel_date,
            "Total Streams": track_info['streams']
        })

    return final_results, cities_data, None

# --- STREAMLIT WEB UI ---
st.set_page_config(page_title="Spotify Stream Scraper", layout="wide") 

st.title("🎧 Spotify Stream Scraper")
st.write("Enter an artist's name or paste their Spotify link below to fetch their top tracks and locations.")

artist_input = st.text_input("Artist Name or Link:")

if st.button("Fetch Artist Data", type="primary"):
    if not artist_input:
        st.warning("Please provide an Artist Name or Spotify Link.")
    else:
        with st.spinner(f"Fetching data for {artist_input}... this takes about 15-20 seconds."):
            try:
                results, cities, error_msg = asyncio.run(perform_search(artist_input))
                
                if error_msg:
                    st.error(error_msg)
                elif results:
                    st.success("Successfully fetched data!")
                    
                    col1, col2 = st.columns([2.5, 1])
                    
                    with col1:
                        st.subheader("🎵 Top 10 Popular Tracks")
                        df = pd.DataFrame(results)
                        st.dataframe(df, width=1500, hide_index=True)
                        
                        csv = df.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Download Data as CSV",
                            data=csv,
                            file_name=f"{artist_input.replace(' ', '_')}_spotify_data.csv",
                            mime="text/csv",
                        )
                        
                    with col2:
                        st.subheader("🌍 Where People Listen")
                        if cities:
                            for city_info in cities:
                                st.metric(label=city_info["City"], value=city_info["Listeners"])
                        else:
                            st.info("Location data not found. Spotify may be blocking the scraper for this artist, or the section is hidden.")
                            
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
