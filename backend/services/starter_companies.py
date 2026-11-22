"""Starter companies (Phase 2.7 A2): companies hiring software / AI / backend engineers in India
whose job board is on Greenhouse, Lever, Ashby or SmartRecruiters.

Drafted 2026-11-20 from web search only (the exact board URL was seen in search results; no
board or API was fetched). Each is added **switched off**: Companies -> Check shows how many
India jobs matching your roles it has right now; switch on the ones worth it. Wrong or dead
boards show an error on Check: delete them. Board ids are case-sensitive.

Each row: name, url (the board link), note (India cities seen in the evidence).
"""
from __future__ import annotations

STARTER: list[dict] = [
    # Greenhouse
    {"name": "PhonePe", "url": "https://job-boards.greenhouse.io/phonepe", "note": "Bengaluru"},
    {"name": "Postman", "url": "https://job-boards.greenhouse.io/postman", "note": "Bengaluru"},
    {"name": "Razorpay", "url": "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited", "note": "Bengaluru"},
    {"name": "Groww", "url": "https://job-boards.eu.greenhouse.io/groww", "note": "Bengaluru; Greenhouse EU board"},
    {"name": "HackerRank", "url": "https://job-boards.greenhouse.io/hackerrank", "note": "Bengaluru"},
    {"name": "Smartsheet", "url": "https://job-boards.greenhouse.io/smartsheet", "note": "Bengaluru"},
    {"name": "Twilio", "url": "https://job-boards.greenhouse.io/twilio", "note": "Bengaluru"},
    {"name": "Glean", "url": "https://job-boards.greenhouse.io/gleanwork", "note": "Bengaluru"},
    {"name": "project44", "url": "https://job-boards.greenhouse.io/project44", "note": "Bengaluru"},
    {"name": "Skild AI", "url": "https://job-boards.greenhouse.io/skildai-careers", "note": "Bengaluru"},
    {"name": "Sumo Logic", "url": "https://job-boards.greenhouse.io/sumologic", "note": "Noida, Bengaluru"},
    {"name": "Capco", "url": "https://job-boards.greenhouse.io/capco", "note": "Pune, Bengaluru"},
    # Lever
    {"name": "Meesho", "url": "https://jobs.lever.co/meesho", "note": "Bengaluru"},
    {"name": "CRED", "url": "https://jobs.lever.co/cred", "note": "Bengaluru"},
    {"name": "Fi (Epifi)", "url": "https://jobs.lever.co/epifi", "note": "Bengaluru"},
    {"name": "ConverseNow", "url": "https://jobs.lever.co/ConverseNow", "note": "Bengaluru"},
    {"name": "Zuma", "url": "https://jobs.lever.co/getzuma", "note": "Bengaluru"},
    {"name": "Acceldata", "url": "https://jobs.lever.co/acceldata", "note": "India (city not seen)"},
    {"name": "KlearNow", "url": "https://jobs.lever.co/klearnow", "note": "Gurugram"},
    {"name": "Portcast", "url": "https://jobs.lever.co/portcast", "note": "Bengaluru, Hyderabad, Chennai, Mumbai, Delhi"},
    {"name": "Netomi", "url": "https://jobs.lever.co/netomi", "note": "Remote India"},
    # Ashby
    {"name": "Harvey", "url": "https://jobs.ashbyhq.com/harvey", "note": "Bengaluru"},
    {"name": "Sarvam AI", "url": "https://jobs.ashbyhq.com/sarvam", "note": "Bengaluru"},
    {"name": "AiPrise", "url": "https://jobs.ashbyhq.com/aiprise", "note": "Bengaluru"},
    {"name": "Ema", "url": "https://jobs.ashbyhq.com/ema", "note": "Bengaluru"},
    {"name": "Granica", "url": "https://jobs.ashbyhq.com/granica", "note": "Bengaluru"},
    {"name": "Level AI", "url": "https://jobs.ashbyhq.com/level-ai", "note": "Noida, Bengaluru"},
    {"name": "Ciroos", "url": "https://jobs.ashbyhq.com/ciroos", "note": "Bengaluru, Gurugram"},
    {"name": "SPAN", "url": "https://jobs.ashbyhq.com/span", "note": "Bengaluru"},
    # SmartRecruiters (applying may need an account, depending on the company)
    {"name": "Freshworks", "url": "https://careers.smartrecruiters.com/Freshworks", "note": "Chennai"},
    {"name": "Visa", "url": "https://jobs.smartrecruiters.com/Visa", "note": "Bengaluru"},
    {"name": "LinkedIn", "url": "https://jobs.smartrecruiters.com/LinkedIn3", "note": "Bengaluru"},
    {"name": "ixigo", "url": "https://jobs.smartrecruiters.com/ixigo", "note": "Gurugram"},
    {"name": "Eurofins", "url": "https://jobs.smartrecruiters.com/Eurofins", "note": "Bengaluru"},
]
