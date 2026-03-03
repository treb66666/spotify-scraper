import streamlit as st
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
import os
import json
import subprocess
import sys

# Install Playwright browsers at runtime (required on Streamlit Cloud)
@st.cache_resource
def install_playwright():
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True
    )
    return result.returncode == 0

async def get_spotify_streams_playwright(artist_id):
    from playwright.async_api import async_playwright

    url = f"https://open.spotify.com/artist/{artist_id}"
    tracks = []
    cities_data = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        if os.path.exists("cookies.json"):
            with open("cookies.json", "r") as f:
                cookies = json.load(f)
                await context.add_cookies(cookies)
            
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # --- TRACK SCRAPING ---
            rows = await page.query_selector_all('[data-testid="tracklist-row"]')
            for row in rows[:10]:
                text = await row.inner_text()
                parts = [p.strip() for p in text.split('\n') if p.strip()]
                if len(parts) >= 2:
                    name = parts[0]
                    streams = "Unknown"
                    for p in parts:
                        if p.replace(',', '').isdigit() and len(p) > 3:
                            streams = p
                            break
                    tracks.append({'name': name, 'streams': streams})

            # --- LOCATION SCRAPING ---
            for _ in range(5):
                await page.mouse.wheel(0, 1000)
                await page.wait_for_timeout(600)

            about_card = page.locator('section[data-testid="about"]')
            if await about_card.count() > 0:
                await about_card.click(force=True)
                await page.wait_for_timeout(3000)

                body_text = await page.inner_text('body')
                if "Where people listen" in body_text:
                    lines = [l.strip() for l in body_text.split("Where people listen")[1].split('\n') if l.strip()]
                    for i, line in enumerate(lines):
                        if "listeners" in line.lower() and i > 0:
                            city = lines[i-1]
                            if not city.isdigit():
                                count = line.replace("listeners", "").strip()
                                if len(cities_data) < 5:
                                    cities_data.append({"City": city, "Listeners": count})

            if not cities_data:
                await page.screenshot(path="debug_screenshot.png")

        except Exception as e:
            st.error(f"Scraper encountered an issue: {e}")
        finally:
            await browser.close()
            
    return tracks, cities_data

def get_release_date(sp, artist_name, track_name):
    try:
        res = sp.search(q=f"artist:{artist_name} track:{track_name}", type='track', limit=1)
        if res['tracks']['items']:
            return res['tracks']['items'][0]['album']['release_date']
    except:
        pass
    return "Unknown"

async def perform_search(artist_input):
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id="1d7660677d5b4567b86bfa2d730eacd7",
        client_secret="37a4d9cd968e43ad851074944d2df8e7"
    ))

    try:
        if "artist/" in artist_input:
            artist_id = artist_input.split("artist/")[1].split("?")[0]
        else:
            search = sp.search(q=artist_input, type='artist', limit=1)
            artist_id = search['artists']['items'][0]['id']
        
        artist_name = sp.artist(artist_id)['name']
        tracks_raw, cities = await get_spotify_streams_playwright(artist_id)
        
        final_results = []
        for t in tracks_raw:
            date = get_release_date(sp, artist_name, t['name'])
            final_results.append({"Track Name": t['name'], "Release Date": date, "Total Streams": t['streams']})
            
        return final_results, cities, None
    except Exception as e:
        return None, None, str(e)

# --- UI ---
st.set_page_config(page_title="Spotify Pro Scraper")
st.title("🎧 Spotify Artist Insights")

# Install Playwright Chromium on startup (cached so it only runs once)
with st.spinner("Initializing browser engine..."):
    installed = install_playwright()
    if not installed:
        st.warning("Browser installation may have had issues. Proceeding anyway...")

query = st.text_input("Enter Artist Name or URL")

if st.button("Get Data"):
    with st.spinner("Accessing Spotify..."):
        results, cities, err = asyncio.run(perform_search(query))
        if err:
            st.error(f"Error: {err}")
        else:
            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader("Top Tracks")
                st.dataframe(pd.DataFrame(results))
            with c2:
                st.subheader("Top Cities")
                for c in cities:
                    st.write(f"**{c['City']}**: {c['Listeners']}")
                if not cities and os.path.exists("debug_screenshot.png"):
                    st.image("debug_screenshot.png")
