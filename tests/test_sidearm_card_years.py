"""Sidearm pages that hold the roster twice (Lamar, Linfield, Bates, Hamilton, Puget Sound): the classic
list has no class year, the card view further down does. The classic parser takes the year from the cards."""
from bs4 import BeautifulSoup

from sidearm import parse_sidearm_classic

PAGE = """
<ul class="sidearm-roster-players">
  <li class="sidearm-roster-player" data-player-id="20891">
    <div class="sidearm-roster-player-name"><h3><a href="/sports/football/roster/xavier-coleman/20891">Xavier Coleman</a></h3></div>
    <span class="sidearm-roster-player-position-long-short">Running Back</span>
    <div class="sidearm-roster-player-class-hometown">
      <span class="sidearm-roster-player-hometown">Willingboro, N.J.</span>
      <span class="sidearm-roster-player-highschool">Lenape HS</span>
    </div>
  </li>
  <li class="sidearm-roster-player" data-player-id="20900">
    <div class="sidearm-roster-player-name"><h3><a href="/sports/football/roster/sam-lee/20900">Sam Lee</a></h3></div>
    <div class="sidearm-roster-player-class-hometown">
      <span class="sidearm-roster-player-hometown">Beaumont, Texas</span>
    </div>
  </li>
  <li class="sidearm-roster-player" data-player-id="20950">
    <div class="sidearm-roster-player-name"><h3><a href="/sports/football/roster/joe-ray/20950">Joe Ray</a></h3></div>
    <span class="sidearm-roster-player-academic-year">Sr.</span>
  </li>
</ul>
<ul class="sidearm-list-card-template-1">
  <li class="sidearm-list-card-item" data-player-id="20891">
    <a class="sidearm-roster-player-name" href="/sports/football/roster/xavier-coleman/20891">Xavier Coleman</a>
    <span class="sidearm-roster-player-academic-year">Jr.</span>
  </li>
  <li class="sidearm-list-card-item">
    <a class="sidearm-roster-player-name" href="/sports/football/roster/sam-lee/20900/">Sam Lee</a>
    <span class="sidearm-roster-player-academic-year">Fy.</span>
  </li>
  <li class="sidearm-list-card-item" data-player-id="20950">
    <a class="sidearm-roster-player-name" href="/sports/football/roster/joe-ray/20950">Joe Ray</a>
    <span class="sidearm-roster-player-academic-year">Jr.</span>
  </li>
</ul>
"""


def test_class_year_from_card_view():
    players = {p["name"]: p for p in parse_sidearm_classic(PAGE, BeautifulSoup(PAGE, "lxml"))}
    assert players["Xavier Coleman"]["class_year"] == "Jr."      # matched by player id
    assert players["Sam Lee"]["class_year"] == "Fy."             # matched by page link
    assert players["Joe Ray"]["class_year"] == "Sr."             # the list's own year is kept
    assert players["Xavier Coleman"]["hometown"] == "Willingboro, N.J."
    assert "_player_id" not in players["Xavier Coleman"]
