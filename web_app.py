import streamlit as st
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from playwright.async_api import async_playwright
import pandas as pd
import os
import json

# NO os.system("playwright install") here anymore!

async def get_spotify_streams_playwright(artist_id):
    # Constructing the URL safely
    url = f"https://open.spotify.com/artist/{artist_id}"
    
    tracks = []
    cities_data = []
    
    async with async_playwright() as p:
        # We tell it where to find the Chromium we installed via packages.txt
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        if os.path.exists("cookies.json"):
            with open("cookies.json", "r") as f:
                cookies = json.load(f)
                await context.add_cookies(cookies)
            
        page = await context.new_page()
        
        try:
            # Go to page and wait for things to settle
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # --- SCRAPE TRACKS ---
            rows = await page.query_selector_all('[data-testid="tracklist-row"]')
            for row in rows[:10]:
                try:
                    text = await row.inner_text()
                    parts = [p.strip() for p in text.split('\n') if p.strip()]
                    if len(parts) >= 2:
                        name = parts[0]
                        # Look for the stream count (usually a long number string)
                        streams = "Unknown"
                        for p in parts:
                            if p.replace(',', '').isdigit() and len(p) > 3:
                                streams = p
                                break
                        tracks.append({'name': name, 'streams': streams})
                except:
                    continue

            # --- SCRAPE LOCATIONS ---
            # Scroll down to reveal the "About" card
            for _ in range(6):
                await page.mouse.wheel(0, 1000)
                await page.wait_for_timeout(700)

            # Target the "About" section specifically
            about_card = page.locator('section[data-testid="about"]')
            if await about_card.count() > 0:
                # Force click the card to open the modal
                await about_card.click(force=True)
                await page.wait_for_timeout(4000) # Wait for popup

                # Get text from the modal
                dialog = page.locator('[role="dialog"]')
                if await dialog.count() > 0:
                    body_text = await dialog.inner_text()
                else:
                    body_text = await page.inner_text('body')

                if "Where people listen" in body_text:
                    # Logic to extract City and Listeners
                    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
                    for i, line in enumerate(lines):
                        if "listeners" in line.lower() and "monthly" not in line.lower():
                            city = lines[i-1]
                            count = line.replace("listeners", "").strip()
                            if not city.isdigit() and len(cities_data) < 5:
                                cities_data.append({"City": city, "Listeners": count})

            # Screenshot if we failed to get cities
            if not cities_data:
                await page.screenshot(path="debug_screenshot.png")

        except Exception as e:
            st.error(f"Scraper Error: {e}")
        finally:
            await browser.close()
            
    return tracks, cities_data

def get_release_date_from_spotify(sp, artist_name, track_name):
    try:
        query = f"artist:{artist_name} track:{track_name}"
        res = sp.search(q=query, type='track', limit=1)
        if res['tracks']['items']:
            return res['tracks']['items'][0]['album']['release_date']
    except:
        pass
    return "Unknown"

async def perform_search(artist_input):
    CLIENT_ID = "1d7660677d5b4567b86bfa2d730eacd7"
    CLIENT_SECRET = "37a4d9cd968e43ad851074944d2df8e7"
    
    auth_manager = SpotifyClientCredentials(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    try:
        # Resolve Artist ID
        if "artist/" in artist_input:
            artist_id = artist_input.split("artist/")[1].split("?")[0]
        else:
            search = sp.search(q=artist_input, type='artist', limit=1)
            artist_id = search['artists']['items'][0]['id']
        
        artist_info = sp.artist(artist_id)
        artist_name = artist_info['name']
        
        tracks_raw, cities = await get_spotify_streams_playwright(artist_id)
        
        final_results = []
        for t in tracks_raw:
            rel_date = get_release_date_from_spotify(sp, artist_name, t['name'])
            final_results.append({
                "Track Name": t['name'],
                "Release Date": rel_date,
                "Total Streams": t['streams']
            })
            
        return final_results, cities, None
    except Exception as e:
        return None, None, str(e)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Spotify Insights", layout="wide")
st.title("🎧 Spotify Artist Insights")

artist_query = st.text_input("Enter Artist Name or Spotify URL")

if st.button("Fetch Data"):
    if not artist_query:
        st.error("Please enter an artist.")
    else:
        with st.spinner("Analyzing Spotify page... (15-20 seconds)"):
            results, cities, err = asyncio.run(perform_search(artist_query))
            
            if err:
                st.error(f"Search failed: {err}")
            else:
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.subheader("Top 10 Tracks")
                    st.table(pd.DataFrame(results))
                with col2:
                    st.subheader("Top Cities")
                    if cities:
                        for c in cities:
                            st.metric(label=c['City'], value=c['Listeners'])
                    else:
                        st.write("Could not find city data.")
                        if os.path.exists("debug_screenshot.png"):
                            st.image("debug_screenshot.png", caption="Bot's View")
