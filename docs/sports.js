// Each sport's words on the three player map pages: the browser tab's title, the search description, the
// heading and the subtitle, and she/her for women's sports. One set of pages serves every sport since Oct 30
// (players-dotmap.html?sport=softball); common.js puts these words in. To add a sport, add its entry here
// (and run python3 scripts/build.py pages, which makes the old-address pages that forward).
window.SPORT_PAGES = {
  "baseball": {
    women: false,
    "players-dotmap": {"title": "College Baseball Recruiting Map", "description": "Where every varsity college baseball player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Baseball <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college baseball player since 2016"},
    "players-heatmap": {"title": "College Baseball Recruiting Footprints", "description": "Compare where up to four college baseball programs, from Division I to junior college, find their players, state by state.", "h1": "College Baseball <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Baseball Transfer Map", "description": "Where college baseball players transferred, school to school, since 2016.", "h1": "College Baseball <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "basketball-mens": {
    women: false,
    "players-dotmap": {"title": "College Basketball (Men's) Recruiting Map", "description": "Where every varsity college men's basketball player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Basketball (Men's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college men's basketball player since 2016"},
    "players-heatmap": {"title": "College Basketball (Men's) Recruiting Footprints", "description": "Compare where up to four college men's basketball programs, from Division I to junior college, find their players, state by state.", "h1": "College Basketball (Men's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Basketball (Men's) Transfer Map", "description": "Where college men's basketball players transferred, school to school, since 2016.", "h1": "College Basketball (Men's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "basketball-womens": {
    women: true,
    "players-dotmap": {"title": "College Basketball (Women's) Recruiting Map", "description": "Where every varsity college women's basketball player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Basketball (Women's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college women's basketball player since 2016"},
    "players-heatmap": {"title": "College Basketball (Women's) Recruiting Footprints", "description": "Compare where up to four college women's basketball programs, from Division I to junior college, find their players, state by state.", "h1": "College Basketball (Women's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Basketball (Women's) Transfer Map", "description": "Where college women's basketball players transferred, school to school, since 2016.", "h1": "College Basketball (Women's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "football": {
    women: false,
    "players-dotmap": {"title": "College Football Recruiting Map", "description": "Where every college football player since 2016 comes from, mapped: FBS, FCS, Division II, Division III, NAIA and junior college.", "h1": "College Football <span>Recruiting Map</span>", "sub": "Hometowns of every college football player since 2016"},
    "players-heatmap": {"title": "College Football Recruiting Footprints", "description": "Compare where up to four college football programs, from FBS to junior college, find their players, state by state.", "h1": "College Football <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Football Transfer Map", "description": "Where college football players transferred, school to school, since 2016.", "h1": "College Football <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "hockey-mens": {
    women: false,
    "players-dotmap": {"title": "College Hockey (Men's) Recruiting Map", "description": "Where every varsity college men's ice hockey player since 2016 comes from, mapped: Division I, II and III.", "h1": "College Hockey (Men's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college men's ice hockey player since 2016"},
    "players-heatmap": {"title": "College Hockey (Men's) Recruiting Footprints", "description": "Compare where up to four college men's ice hockey programs, from Division I to Division III, find their players, state by state.", "h1": "College Hockey (Men's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Hockey (Men's) Transfer Map", "description": "Where college men's ice hockey players transferred, school to school, since 2016.", "h1": "College Hockey (Men's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "hockey-womens": {
    women: true,
    "players-dotmap": {"title": "College Hockey (Women's) Recruiting Map", "description": "Where every varsity college women's ice hockey player since 2016 comes from, mapped: Division I, II and III.", "h1": "College Hockey (Women's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college women's ice hockey player since 2016"},
    "players-heatmap": {"title": "College Hockey (Women's) Recruiting Footprints", "description": "Compare where up to four college women's ice hockey programs, from Division I to Division III, find their players, state by state.", "h1": "College Hockey (Women's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Hockey (Women's) Transfer Map", "description": "Where college women's ice hockey players transferred, school to school, since 2016.", "h1": "College Hockey (Women's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "lacrosse-mens": {
    women: false,
    "players-dotmap": {"title": "College Lacrosse (Men's) Recruiting Map", "description": "Where every varsity college men's lacrosse player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Lacrosse (Men's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college men's lacrosse player since 2016"},
    "players-heatmap": {"title": "College Lacrosse (Men's) Recruiting Footprints", "description": "Compare where up to four college men's lacrosse programs, from Division I to junior college, find their players, state by state.", "h1": "College Lacrosse (Men's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Lacrosse (Men's) Transfer Map", "description": "Where college men's lacrosse players transferred, school to school, since 2016.", "h1": "College Lacrosse (Men's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "lacrosse-womens": {
    women: true,
    "players-dotmap": {"title": "College Lacrosse (Women's) Recruiting Map", "description": "Where every varsity college women's lacrosse player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Lacrosse (Women's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college women's lacrosse player since 2016"},
    "players-heatmap": {"title": "College Lacrosse (Women's) Recruiting Footprints", "description": "Compare where up to four college women's lacrosse programs, from Division I to junior college, find their players, state by state.", "h1": "College Lacrosse (Women's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Lacrosse (Women's) Transfer Map", "description": "Where college women's lacrosse players transferred, school to school, since 2016.", "h1": "College Lacrosse (Women's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "soccer-mens": {
    women: false,
    "players-dotmap": {"title": "College Soccer (Men's) Recruiting Map", "description": "Where every varsity college men's soccer player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Soccer (Men's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college men's soccer player since 2016"},
    "players-heatmap": {"title": "College Soccer (Men's) Recruiting Footprints", "description": "Compare where up to four college men's soccer programs, from Division I to junior college, find their players, state by state.", "h1": "College Soccer (Men's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Soccer (Men's) Transfer Map", "description": "Where college men's soccer players transferred, school to school, since 2016.", "h1": "College Soccer (Men's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "soccer-womens": {
    women: true,
    "players-dotmap": {"title": "College Soccer (Women's) Recruiting Map", "description": "Where every varsity college women's soccer player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Soccer (Women's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college women's soccer player since 2016"},
    "players-heatmap": {"title": "College Soccer (Women's) Recruiting Footprints", "description": "Compare where up to four college women's soccer programs, from Division I to junior college, find their players, state by state.", "h1": "College Soccer (Women's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Soccer (Women's) Transfer Map", "description": "Where college women's soccer players transferred, school to school, since 2016.", "h1": "College Soccer (Women's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "softball": {
    women: true,
    "players-dotmap": {"title": "College Softball Recruiting Map", "description": "Where every varsity college softball player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Softball <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college softball player since 2016"},
    "players-heatmap": {"title": "College Softball Recruiting Footprints", "description": "Compare where up to four college softball programs, from Division I to junior college, find their players, state by state.", "h1": "College Softball <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Softball Transfer Map", "description": "Where college softball players transferred, school to school, since 2016.", "h1": "College Softball <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
  "volleyball-womens": {
    women: true,
    "players-dotmap": {"title": "College Volleyball (Women's) Recruiting Map", "description": "Where every varsity college women's volleyball player since 2016 comes from, mapped: Division I, II and III, NAIA and junior college.", "h1": "College Volleyball (Women's) <span>Recruiting Map</span>", "sub": "Hometowns of every varsity college women's volleyball player since 2016"},
    "players-heatmap": {"title": "College Volleyball (Women's) Recruiting Footprints", "description": "Compare where up to four college women's volleyball programs, from Division I to junior college, find their players, state by state.", "h1": "College Volleyball (Women's) <span>Recruiting Footprints</span>"},
    "players-transfers": {"title": "College Volleyball (Women's) Transfer Map", "description": "Where college women's volleyball players transferred, school to school, since 2016.", "h1": "College Volleyball (Women's) <span>Transfer Map</span>", "sub": "Where players moved from school to school since 2016"},
  },
};
