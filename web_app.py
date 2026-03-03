import streamlit as st
import asyncio
from datetime import datetime
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from playwright.async_api import async_playwright
import pandas as pd
import os

# Tell the cloud server to install the hidden browser
os.system("playwright install chromium")
os.system("playwright install-deps chromium")

# --- CORE LOGIC ---
async def get_spotify_streams_playwright(artist_id):
    url = f"https://open.spotify.com/artist/{artist_id}"
    tracks = []
    cities_data = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_selector('[data-testid="tracklist-row"]', timeout=10000)
            await page.wait_for_timeout(2000)
            
            # 1. SCRAPE THE TRACKS
            try:
                button = page.locator('button:has-text("See more")')
                if await button.count() > 0:
                    await button.first.click()
                    await page.wait_for_timeout(1000)
                else:
                    button2 = page.locator('button:has-text("Show more")')
                    if await button2.count() > 0:
                        await button2.first.click()
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
                    
            # 2. SCRAPE "WHERE PEOPLE LISTEN" (Top Locations)
            try:
                # Scroll down the page to trigger the lazy-loading of the bottom sections
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(1000)
                await page.evaluate("window.scrollBy(0, 1500)")
                await page.wait_for_timeout(1500)
                
                # Attempt to click an "About" tab just in case it is hidden there
                about_tab = page.locator('button:has-text("About"), a:has-text("About")')
                if await about_tab.count() > 0:
                    for i in range(await about_tab.count()):
                        try:
                            await about_tab.nth(i).click(timeout=1000)
                            await page.wait_for_timeout(1500)
                        except:
                            pass

                # Extract the raw text from the page to find the cities
                body_text = await page.inner_text('body')
                if "Where people listen" in body_text:
                    section_text = body_text.split("Where people listen")[1]
                    # Read the next ~40 lines to capture the 5 cities
                    lines = [line.strip() for line in section_text.split('\n') if line.strip()][:40]
                    
                    for i, line in enumerate(lines):
                        if "listeners" in line.lower():
                            # Handle different formatting scenarios
                            if line.lower() == "listeners" and i > 0:
                                listeners_count = lines[i-1] + " listeners"
                                city_line = lines[i-2] if i >= 2 else ""
                                if city_line.isdigit() and i >= 3:
                                    city_line = lines[i-3]
                            else:
                                listeners_count = line
                                city_line = lines[i-1] if i >= 1 else ""
                                if city_line.isdigit() and i >= 2:
                                    city_line = lines[i-2]
                            
                            # Clean up and add to list
                            if city_line and city_line.lower() != "where people listen":
                                if not any(c["City"] == city_line for c in cities_data):
                                    clean_listeners = listeners_count.lower().replace("listeners", "").strip()
                                    cities_data.append({"City": city_line, "Listeners": clean_listeners})
                                if len(cities_data) == 5:
                                    break
            except Exception:
                pass # If the artist is too small to have this section, we gracefully skip it

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

    if "spotify.com/artist/" in artist_input:
        artist_id = artist_input.split("artist/")[1].split("?")[0]
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

    # Unpack the new cities data
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
st.set_page_config(page_title="Spotify Stream Scraper", layout="wide") # Changed to wide to fit 5 cities nicely

st.title("🎧 Spotify Stream Scraper")
st.write("Enter an artist's name or paste their Spotify link below to fetch their top tracks and locations.")

artist_input = st.text_input("Artist Name or Link:")

if st.button("Fetch Artist Data", type="primary"):
    if not artist_input:
        st.warning("Please provide an Artist Name or Spotify Link.")
    else:
        with st.spinner(f"Fetching data for {artist_input}... this takes about 10-15 seconds."):
            try:
                # Capture the three returned variables
                results, cities, error_msg = asyncio.run(perform_search(artist_input))
                
                if error_msg:
                    st.error(error_msg)
                elif results:
                    st.success("Successfully fetched data!")
                    
                    # If the scraper found the cities, display them in 5 neat columns!
                    if cities:
                        st.subheader("🌍 Where People Listen (Top 5)")
                        cols = st.columns(len(cities))
                        for i, city_info in enumerate(cities):
                            # Streamlit's .metric() makes big, bold numbers that look great on dashboards
                            cols[i].metric(label=city_info["City"], value=city_info["Listeners"])
                        st.divider() # Adds a clean horizontal line
                        
                    st.subheader("🎵 Top 10 Popular Tracks")
                    df = pd.DataFrame(results)
                    st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
