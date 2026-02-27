import streamlit as st
import asyncio
import requests
import urllib.parse
from datetime import datetime
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from playwright.async_api import async_playwright
import pandas as pd
import os

# Tell the cloud server to install the hidden browser
os.system("playwright install chromium")
os.system("playwright install-deps chromium")

# --- CORE LOGIC (Unchanged) ---
async def get_spotify_streams_playwright(artist_id):
# ... (Keep the rest of your code exactly the same)