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
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_selector('[data-testid="tracklist-row"]', timeout=10000)
            await page.wait_for_timeout(2000)
            
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
        except Exception:
            pass 
        finally:
            await browser.close()
            
    return tracks

def get_release_date_from_spotify(sp, artist_name, track_name):
    """Uses the official Spotify API to find the exact release date."""
    # Clean up the track name to ensure a better search match
    clean_track_name = track_name.split('(')[0].split('-')[0].strip()
    query = f"{artist_name} {clean_track_name}"
    
    try:
        # Search Spotify for the specific track
        result = sp.search(q=query, type='track', limit=1)
        tracks = result.get('tracks', {}).get('items', [])
        
        if tracks:
            # Extract the release date from the album the track belongs to
            release_date = tracks[0]['album']['release_date']
            return release_date
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
            return None, f"Artist '{artist_input}' not found."
        artist_data = items[0]
        artist_name = artist_data['name']
        artist_id = artist_data['id']

    top_tracks_data = await get_spotify_streams_playwright(artist_id)
    if not top_tracks_data:
        return None, "Failed to pull track data from the Spotify web page."

    final_results = []
    for idx, track_info in enumerate(top_tracks_data, start=1):
        track_name = track_info['name']
        
        # Now we pass our authenticated Spotify connection (sp) to get the date natively
        rel_date = get_release_date_from_spotify(sp, artist_name, track_name)
        
        final_results.append({
            "Rank": idx,
            "Track Name": track_name,
            "Release Date": rel_date,
            "Total Streams": track_info['streams']
        })

    return final_results, None

# --- STREAMLIT WEB UI ---
st.set_page_config(page_title="Spotify Stream Scraper", layout="centered")

st.title("🎧 Spotify Stream Scraper")
st.write("Enter an artist's name or paste their Spotify link below to fetch their top tracks.")

artist_input = st.text_input("Artist Name or Link:")

if st.button("Fetch Tracks", type="primary"):
    if not artist_input:
        st.warning("Please provide an Artist Name or Spotify Link.")
    else:
        with st.spinner(f"Fetching data for {artist_input}... this takes about 10 seconds."):
            try:
                # Run the async scraping function
                results, error_msg = asyncio.run(perform_search(artist_input))
                
                if error_msg:
                    st.error(error_msg)
                elif results:
                    st.success("Successfully fetched tracks!")
                    # Convert results to a Pandas DataFrame to render a clean web table
                    df = pd.DataFrame(results)
                    st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
