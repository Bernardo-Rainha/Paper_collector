# Paper_collector
A simple Python Script that pulls out paper from three diferents fonts from their respectives APIs. How many you want, (sometimes how many they can provide)

---
# Usage
TThe program has the function of searching for papers from three sources, downloading them and creating a JSON file, saving them in a folder called _BIBLIOTECA\(YYYY--MM-DD)

JSON serves as a library control, it is used to check whether the Articles have already been downloaded, not repeating any and, if it is executed more than once, it passes the limit and continues to the next unseen ones. It is also used to store information about papers, giving freedom to those who want to do their own things later.

The sources have slightly different search modes, but nothing special. They use the same system using key words and/or categories.

The program was ENTIRELY designed as a daily application running on Obsidian software, with its files edited in markdown format with native YMAL. Just put it in your vault and set it to repeat every day or every 7 days. and has a STRONG bias towards computing, engineering, mechanics and physics (you can change the keywords in the script)

---
# Sources

## arXive repository
The arXive had a public API for pull requests and download papers

## NASA NTRS
NASA also have a public API, you can see more on https://ntrs.nasa.gov/api

## Semantic Scholar
The Semantic Scholar API s2 is given by the institution for simply request, However, you may have an academic (or bussines) email. After send the request you'll recive the API by email in a few hours
Link for Semantic Scholar API: https://www.semanticscholar.org/product/api

---
