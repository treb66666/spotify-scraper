import streamlit as st
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from playwright.async_api import async_playwright
import pandas as pd
import os
import json

# Installs the browser for the cloud server
os.system("playwright install chromium")

async def get_spotify_streams_playwright(artist_id):
    # Guaranteed to be the actual, real Spotify URL
    base_url = "https://open.spotify.com/artist/"
    url = f"{base_url}{artist_id}"
    
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

        # Load your cookies if you uploaded them
        try:
            if os.path.exists("cookies.json"):
                with open("cookies.json", "r") as f:
                    raw_cookies = json.load(f)
                    valid_cookies = [{"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c["path"]} for c in raw_cookies]
                    await context.add_cookies(valid_cookies)
        except:
            pass 
            
        page = await context.new_page()
        
        try:
            # Go to the site and wait for the network to settle
            await page.goto(url, wait_until="networkidle", timeout=20000)
            
            # --- DIAGNOSTIC SCREENSHOT ---
            # We take a screenshot immediately to see what the bot is looking at
            await page.screenshot(path="debug_screenshot.png")
            
            # Destroy popups blocking the screen
            await page.evaluate("""
                document.querySelectorAll('[data-testid="login-button"], [id^="onetrust"], .GenericModal, [role="dialog"]').forEach(el => el.remove());
            """)
            await page.wait_for_timeout(1000)
            
            # --- 1. SCRAPE TRACKS ---
            try:
                # Expand the tracks list
                await page.evaluate("""
                    const btns = Array.from(document.querySelectorAll('button'));
                    const moreBtn = btns.find(b => b.innerText.includes('See more') || b.innerText.includes('Show more'));
                    if(moreBtn) moreBtn.click();
                """)
                await page.wait_for_timeout(1500)
                
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
                
            # --- 2. SCRAPE LOCATIONS ---
            try:
                # Aggressively scroll down
                for _ in range(6):
                    await page.mouse.wheel(0, 1000)
                    await page.wait_for_timeout(800)

                # Try to click the "About" section
                await page.evaluate("""
                    const aboutSection = document.querySelector('section[data-testid="about"]');
                    if (aboutSection) { aboutSection.click(); }
                    else {
                        const headers = Array.from(document.querySelectorAll('h2, h3, div'));
                        const aboutHeader = headers.find(el => el.innerText === 'About');
                        if (aboutHeader) aboutHeader.click();
                    }
                """)
                await page.wait_for_timeout(2500) 

                # Grab all text on the screen
                body_text = await page.inner_text('body')

                # Parse the cities
                if "Where people listen" in body_text:
                    section_text = body_text.split("Where people listen")[1]
                    lines = [line.strip() for line in section_text.split('\n') if line.strip()]
                    
                    for i, line in enumerate(lines):
                        if "listeners" in line.lower() and "monthly" not in line.lower():
                            city = lines[i-1]
                            listeners = line.lower().replace("listeners", "").strip()
                            
                            if city and not city.isdigit() and "Where people listen" not in city and "About" not in city:
                                if not any(c["City"] == city for c in cities_data):
                                    cities_data.append({"City": city, "Listeners": listeners})
                                    
                        if len(cities_data) == 5:
                            break
            except Exception:
                pass 
                
            # Update the screenshot one last time to capture the final state
            await page.screenshot(path="debug_screenshot.png")

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

    # Fixed to recognize real Spotify links properly
    if "http" in artist_input or "spotify:artist:" in artist_input:
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

    # Delete old screenshot
    if os.path.exists("debug_screenshot.png"):
        os.remove("debug_screenshot.png")

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
        with st.spinner(f"Fetching data for {artist_input}... this takes about 10-15 seconds."):
            try:
                results, cities, error_msg = asyncio.run(perform_search(artist_input))
                
                # --- NEW DIAGNOSTIC UI ---
                # Always show the screenshot if it exists so we can see what happened!
                if os.path.exists("debug_screenshot.png"):
                    st.warning("📷 **Bot Vision:** Here is exactly what the bot saw on the webpage.")
                    st.image("debug_screenshot.png", width=800)

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
                            st.info("Location data not found or hidden for this artist.")
                            
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
