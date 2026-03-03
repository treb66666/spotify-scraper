import streamlit as st
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from playwright.async_api import async_playwright
import pandas as pd
import os
import json

# Remove os.system("playwright install chromium") - handled by Streamlit Cloud now

async def get_spotify_streams_playwright(artist_id):
    # Construct URL safely to avoid auto-formatting issues
    base = "https://open.spotify.com/artist/"
    url = f"{base}{artist_id}"
    
    tracks = []
    cities_data = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        # Load Cookies
        if os.path.exists("cookies.json"):
            with open("cookies.json", "r") as f:
                cookies = json.load(f)
                await context.add_cookies(cookies)
            
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # 1. SCRAPE TRACKS
            rows = await page.query_selector_all('[data-testid="tracklist-row"]')
            for row in rows[:10]:
                text = await row.inner_text()
                parts = [p.strip() for p in text.split('\n') if p.strip()]
                if len(parts) >= 2:
                    # Logic to find the number (streams) and the name
                    streams = "Unknown"
                    for p in parts:
                        if p.replace(',', '').isdigit():
                            streams = p
                            break
                    tracks.append({'name': parts[0], 'streams': streams})

            # 2. SCRAPE LOCATIONS (The "About" Section)
            # Scroll to find the About section
            for _ in range(5):
                await page.mouse.wheel(0, 800)
                await page.wait_for_timeout(500)

            # Click the About Card
            about_selectors = [
                'section[data-testid="about"]',
                'div[role="button"]:has-text("Monthly Listeners")',
                'button:has-text("About")'
            ]
            
            clicked = False
            for selector in about_selectors:
                if await page.locator(selector).count() > 0:
                    await page.click(selector, force=True, timeout=5000)
                    clicked = True
                    break
            
            if clicked:
                await page.wait_for_timeout(3000) # Wait for modal
                
                # Look for city data in the popup
                dialog = page.locator('[role="dialog"]')
                body_text = await dialog.inner_text() if await dialog.count() > 0 else await page.inner_text('body')

                if "Where people listen" in body_text:
                    parts = body_text.split("Where people listen")[1].split('\n')
                    clean_parts = [x.strip() for x in parts if x.strip() and "listeners" not in x.lower()]
                    
                    # Grouping City and Numbers
                    for i in range(0, len(clean_parts)-1, 2):
                        city = clean_parts[i]
                        listeners = clean_parts[i+1]
                        if not city.isdigit() and len(cities_data) < 5:
                            cities_data.append({"City": city, "Listeners": listeners})

            # Screenshot if locations fail
            if not cities_data:
                await page.screenshot(path="debug_screenshot.png")

        except Exception as e:
            st.error(f"Scraper Error: {e}")
        finally:
            await browser.close()
            
    return tracks, cities_data

# ... [Keep your existing spotipy auth and perform_search functions here] ...

def get_release_date_from_spotify(sp, artist_name, track_name):
    query = f"{artist_name} {track_name}"
    try:
        result = sp.search(q=query, type='track', limit=1)
        if result['tracks']['items']:
            return result['tracks']['items'][0]['album']['release_date']
    except:
        pass
    return "Unknown"

async def perform_search(artist_input):
    # Use your existing ID and Secret
    CLIENT_ID = "1d7660677d5b4567b86bfa2d730eacd7"
    CLIENT_SECRET = "37a4d9cd968e43ad851074944d2df8e7"
    
    auth_manager = SpotifyClientCredentials(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    try:
        if "artist/" in artist_input:
            artist_id = artist_input.split("artist/")[1].split("?")[0]
        else:
            search = sp.search(q=artist_input, type='artist', limit=1)
            artist_id = search['artists']['items'][0]['id']
            artist_input = search['artists']['items'][0]['name']
        
        artist_name = sp.artist(artist_id)['name']
        
        tracks_raw, cities = await get_spotify_streams_playwright(artist_id)
        
        final_tracks = []
        for t in tracks_raw:
            date = get_release_date_from_spotify(sp, artist_name, t['name'])
            final_tracks.append({"Track Name": t['name'], "Release Date": date, "Total Streams": t['streams']})
            
        return final_tracks, cities, None
    except Exception as e:
        return None, None, str(e)

# --- UI CODE ---
st.title("🎧 Spotify Artist Insights")
artist_query = st.text_input("Artist Name or Link")

if st.button("Run Scraper"):
    with st.spinner("Bypassing security and fetching data..."):
        results, cities, error = asyncio.run(perform_search(artist_query))
        
        if error:
            st.error(error)
            if os.path.exists("debug_screenshot.png"):
                st.image("debug_screenshot.png", caption="What the bot saw")
        else:
            col1, col2 = st.columns([2, 1])
            with col1:
                st.subheader("Top Tracks")
                st.table(pd.DataFrame(results))
            with col2:
                st.subheader("Top Cities")
                for c in cities:
                    st.write(f"**{c['City']}**: {c['Listeners']} listeners")
