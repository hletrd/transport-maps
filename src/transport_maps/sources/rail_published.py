"""Trains timed from their operators' own published timetables, where no open
feed exists (sources/gtfs_rail carries the feeds).

Japan's Shinkansen operators publish no GTFS (ODPT's railway datasets carry
JR East's Kanto conventional lines, not one Shinkansen), and the OSM relations
price them by tier: Shin-Osaka -> Hiroshima rode in 98 min against the 79 the
fastest Nozomi takes, Tokyo -> Sendai in 86 against 90. But each operator
publishes every train's calls on its own site, which needs no account. A row
here is one train as its operator's page states it -- the calls at the major
stations it serves, arrival and departure, the page's URL and the date it was
read -- and becomes the same two-stop rows a feed's trips become
(`gtfs_rail.timetable_rows`): every pair of its calls a leg timed
departure(i) -> arrival(j), arriving at the station's alight-only twin. So a
published train is applied exactly as a GTFS trip is: it wins its station
pairs outright (`graph/rail.ride_edges`), and the stations between keep OSM's
relations, which are NOT superseded -- a handful of fastest trains is not an
operator's whole service.

Which trains. Every Shinkansen train leaving Tokyo on JR East's site
(timetables.jreast.co.jp: Tokaido-Sanyo, Tohoku-Hokkaido, Joetsu, Hokuriku;
527 trains) and leaving Hakata on JR Kyushu's (www.jrkyushu-timetable.jp:
Kyushu down, Sanyo-Tokaido up; 146 trains) was read on 2026-10-20 and the
fastest scheduled minutes taken for each pair of the major stations below on
one line. The rows are the fewest of those trains that together come within
1 min of every such fastest time (194 pairs; 17 trains): the table stays
small enough to read against the operators' pages, and the minute it gives
away is under the timetable's own rounding. The calls listed are those
stations only; the other calls the train makes are on its page.

China Railway publishes no feed either, and OSM's relations price its long
hauls fast: Shanghai -> Kunming rode in 539 min against the 575 the fastest
of six direct trains takes, Changchun -> Shanghai in 519 against 562. Its own
timetable query (12306: kyfw.12306.cn, no login) lists every train between
two stations with its running time, and each train's calls. For each of 18
corridors between major cities the fastest direct G/D/C train of 2026-10-22
was taken and its calls at the corridor hubs listed (the hubs: every corridor
end plus the junctions trains change at). A pair two rows time is timed by
the faster; a hub pair no corridor names is timed by whichever listed train
calls at both, which may be a few minutes slower than the fastest train in
the whole timetable -- still a train that runs, where OSM's price was a
guess.

What a row can and cannot correct. It replaces OSM's price between the same
two stations (`graph/rail.ride_edges`), so a corridor OSM prices too SLOW
comes right: Beijing -> Shanghai rode in 270 min and now rides in G25's 258.
But where OSM's relation reaches the two stations through a run of stops, the
chain of its own legs still stands beside the row, and a corridor it prices
too FAST stays too fast: measured on 2026-10-20, Shanghai -> Kunming 539
(G201: 575), Beijing -> Fuzhou 436 (G87: 471), Changchun -> Shanghai 516
(fastest direct: 562). Those need the relations' tier speeds measured
against these rows, not more rows.

Amtrak's GTFS download is not used (sources/gtfs_rail says why), but its
own timetable for the Acela (content.amtrak.com/content/timetable/Acela.pdf,
the 29-page timetable for 2026-10-20) states every train's calls. OSM's
relations priced New York -> Washington at 202 min against the 175 the
fastest Acela takes. The rows are the fewest of its 87 trains that together
come within 1 min of the fastest time between every pair of Washington,
Baltimore, Philadelphia, New York, New Haven, Providence and Boston (21
pairs; 9 trains). The timetable prints one time per call -- the departure,
and the arrival at the last -- so a call's arrival is its departure here: a
ride ending at a station a train dwells at (New York, for trains running
through) reads a few minutes long, and one of the trains ending there times
that pair instead.

Facts from the operators' own timetables only -- no aggregator, no journey
planner -- and every number here can be checked on the page its row cites.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class PublishedTrain:
    """One train as its operator's timetable page states it.

    `calls` are (station, lat, lon, arrive, depart) in calling order, times
    "HH:MM" as printed (a train that runs past midnight continues the day),
    the first call's arrival and the last's departure empty. Positions are
    OSM's for the station, so each call snaps onto the station OSM's
    relations already use (`gtfs_rail.snap`).
    """

    operator: str
    train: str
    tier: str
    calls: tuple[tuple[str, float, float, str, str], ...]
    source: str
    checked: str


CHECKED_JP = "2026-10-20 (the operator's timetable for that day)"
# 12306's train query page; a train's calls are its queryTrainInfo answer
# for the date checked, and the corridor's fastest is its leftTicket answer.
CR_SOURCE = "https://kyfw.12306.cn/otn/queryTrainInfo/init"
CHECKED_CN = "2026-10-20 (12306's timetable for 2026-10-22)"
AMTRAK_SOURCE = "https://content.amtrak.com/content/timetable/Acela.pdf"
CHECKED_US = "2026-10-20 (Amtrak's Acela timetable for that day)"

TRAINS: tuple[PublishedTrain, ...] = (
    PublishedTrain("JR Central / JR West", "のぞみ 64号", "high_speed", (
        ("博多", 33.589788, 130.421116, "", "19:00"),
        ("小倉", 33.887243, 130.883372, "19:15", "19:16"),
        ("広島", 34.398348, 132.475657, "20:01", "20:02"),
        ("岡山", 34.665374, 133.917799, "20:36", "20:37"),
        ("新神戸", 34.706447, 135.195536, "21:08", "21:09"),
        ("新大阪", 34.73386, 135.500945, "21:21", "21:24"),
        ("京都", 34.98461, 135.758451, "21:37", "21:38"),
        ("名古屋", 35.170581, 136.880978, "22:11", "22:12"),
        ("新横浜", 35.507204, 139.617391, "23:27", "23:28"),
        ("品川", 35.628647, 139.74007, "23:38", "23:39"),
        ("東京", 35.681051, 139.767397, "23:45", ""),
    ), "https://www.jrkyushu-timetable.jp/sp/2610/0008/00084901.html", CHECKED_JP),
    PublishedTrain("JR Central / JR West", "のぞみ 1号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "06:00"),
        ("品川", 35.628647, 139.74007, "06:06", "06:07"),
        ("新横浜", 35.507204, 139.617391, "06:17", "06:18"),
        ("名古屋", 35.170581, 136.880978, "07:34", "07:35"),
        ("京都", 34.98461, 135.758451, "08:08", "08:09"),
        ("新大阪", 34.73386, 135.500945, "08:22", "08:24"),
        ("新神戸", 34.706447, 135.195536, "08:36", "08:37"),
        ("岡山", 34.665374, 133.917799, "09:09", "09:10"),
        ("広島", 34.398348, 132.475657, "09:49", "09:50"),
        ("小倉", 33.887243, 130.883372, "10:35", "10:36"),
        ("博多", 33.589788, 130.421116, "10:52", ""),
    ), "https://timetables.jreast.co.jp/2610/train/005/008031.html", CHECKED_JP),
    PublishedTrain("JR East / JR West", "かがやき 503号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "07:20"),
        ("大宮", 35.906094, 139.623014, "07:42", "07:43"),
        ("長野", 36.642766, 138.188893, "08:37", "08:39"),
        ("富山", 36.701368, 137.213444, "09:24", "09:25"),
        ("金沢", 36.578047, 136.64813, "09:44", "09:46"),
        ("福井", 36.061778, 136.223479, "10:09", "10:10"),
        ("敦賀", 35.645031, 136.078082, "10:26", ""),
    ), "https://timetables.jreast.co.jp/2610/train/095/098391.html", CHECKED_JP),
    PublishedTrain("JR West / JR Kyushu", "みずほ 615号", "high_speed", (
        ("新大阪", 34.73386, 135.500945, "", "19:54"),
        ("新神戸", 34.706447, 135.195536, "20:06", "20:06"),
        ("岡山", 34.665374, 133.917799, "20:39", "20:40"),
        ("広島", 34.398348, 132.475657, "21:15", "21:16"),
        ("小倉", 33.887243, 130.883372, "22:02", "22:03"),
        ("博多", 33.589788, 130.421116, "22:18", "22:20"),
        ("熊本", 32.790311, 130.688557, "22:52", "22:53"),
        ("鹿児島中央", 31.58365, 130.542218, "23:44", ""),
    ), "https://www.jrkyushu-timetable.jp/sp/2610/0026/00261101.html", CHECKED_JP),
    PublishedTrain("JR East / JR Hokkaido", "はやぶさ 5号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "08:18"),
        ("大宮", 35.906094, 139.623014, "08:41", "08:42"),
        ("仙台", 38.2599, 140.881988, "09:48", "09:50"),
        ("盛岡", 39.701481, 141.136534, "10:28", "10:29"),
        ("新青森", 40.828259, 140.693472, "11:16", "11:18"),
        ("新函館北斗", 41.90466, 140.648522, "12:15", ""),
    ), "https://timetables.jreast.co.jp/2610/train/110/110951.html", CHECKED_JP),
    PublishedTrain("JR East / JR West", "はくたか 561号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "11:24"),
        ("上野", 35.713091, 139.7773, "11:29", "11:30"),
        ("大宮", 35.906094, 139.623014, "11:48", "11:49"),
        ("高崎", 36.322766, 139.012994, "12:11", "12:12"),
        ("長野", 36.642766, 138.188893, "12:49", "12:51"),
        ("富山", 36.701368, 137.213444, "13:54", "13:55"),
        ("金沢", 36.578047, 136.64813, "14:17", "14:19"),
        ("福井", 36.061778, 136.223479, "14:54", "14:55"),
        ("敦賀", 35.645031, 136.078082, "15:16", ""),
    ), "https://timetables.jreast.co.jp/2610/train/095/098561.html", CHECKED_JP),
    PublishedTrain("JR West / JR Kyushu", "みずほ 600号", "high_speed", (
        ("鹿児島中央", 31.58365, 130.542218, "", "06:27"),
        ("熊本", 32.790311, 130.688557, "07:18", "07:19"),
        ("博多", 33.589788, 130.421116, "07:51", "07:53"),
        ("小倉", 33.887243, 130.883372, "08:09", "08:10"),
        ("広島", 34.398348, 132.475657, "08:55", "08:56"),
        ("岡山", 34.665374, 133.917799, "09:32", "09:33"),
        ("新神戸", 34.706447, 135.195536, "10:07", "10:08"),
        ("新大阪", 34.73386, 135.500945, "10:21", ""),
    ), "https://www.jrkyushu-timetable.jp/sp/2610/0009/00090001.html", CHECKED_JP),
    PublishedTrain("JR Central / JR West", "のぞみ 3号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "06:15"),
        ("品川", 35.628647, 139.74007, "06:21", "06:22"),
        ("新横浜", 35.507204, 139.617391, "06:32", "06:33"),
        ("名古屋", 35.170581, 136.880978, "07:50", "07:51"),
        ("京都", 34.98461, 135.758451, "08:24", "08:26"),
        ("新大阪", 34.73386, 135.500945, "08:39", "08:41"),
        ("新神戸", 34.706447, 135.195536, "08:53", "08:54"),
        ("岡山", 34.665374, 133.917799, "09:25", "09:26"),
        ("広島", 34.398348, 132.475657, "10:02", "10:03"),
        ("小倉", 33.887243, 130.883372, "10:53", "10:54"),
        ("博多", 33.589788, 130.421116, "11:09", ""),
    ), "https://timetables.jreast.co.jp/2610/train/010/011051.html", CHECKED_JP),
    PublishedTrain("JR East / JR Hokkaido", "はやぶさ 23号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "12:20"),
        ("上野", 35.713091, 139.7773, "12:25", "12:26"),
        ("大宮", 35.906094, 139.623014, "12:44", "12:45"),
        ("仙台", 38.2599, 140.881988, "13:51", "13:53"),
        ("盛岡", 39.701481, 141.136534, "14:32", "14:37"),
        ("新青森", 40.828259, 140.693472, "15:29", "15:31"),
        ("新函館北斗", 41.90466, 140.648522, "16:30", ""),
    ), "https://timetables.jreast.co.jp/2610/train/010/010075.html", CHECKED_JP),
    PublishedTrain("JR East / JR West", "かがやき 515号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "18:24"),
        ("上野", 35.713091, 139.7773, "18:29", "18:30"),
        ("大宮", 35.906094, 139.623014, "18:48", "18:49"),
        ("長野", 36.642766, 138.188893, "19:44", "19:46"),
        ("富山", 36.701368, 137.213444, "20:32", "20:33"),
        ("金沢", 36.578047, 136.64813, "20:51", "20:53"),
        ("福井", 36.061778, 136.223479, "21:16", "21:17"),
        ("敦賀", 35.645031, 136.078082, "21:33", ""),
    ), "https://timetables.jreast.co.jp/2610/train/095/098451.html", CHECKED_JP),
    PublishedTrain("JR West / JR Kyushu", "みずほ 610号", "high_speed", (
        ("鹿児島中央", 31.58365, 130.542218, "", "17:45"),
        ("熊本", 32.790311, 130.688557, "18:40", "18:41"),
        ("博多", 33.589788, 130.421116, "19:13", "19:15"),
        ("小倉", 33.887243, 130.883372, "19:30", "19:31"),
        ("広島", 34.398348, 132.475657, "20:16", "20:17"),
        ("岡山", 34.665374, 133.917799, "20:52", "20:53"),
        ("新神戸", 34.706447, 135.195536, "21:24", "21:25"),
        ("新大阪", 34.73386, 135.500945, "21:37", ""),
    ), "https://www.jrkyushu-timetable.jp/sp/2610/0009/00097801.html", CHECKED_JP),
    PublishedTrain("JR Central / JR West", "のぞみ 211号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "18:42"),
        ("品川", 35.628647, 139.74007, "18:48", "18:49"),
        ("新横浜", 35.507204, 139.617391, "18:59", "19:00"),
        ("名古屋", 35.170581, 136.880978, "20:22", "20:23"),
        ("京都", 34.98461, 135.758451, "20:57", "20:59"),
        ("新大阪", 34.73386, 135.500945, "21:12", "21:14"),
        ("新神戸", 34.706447, 135.195536, "21:26", "21:27"),
        ("岡山", 34.665374, 133.917799, "21:58", "21:59"),
        ("広島", 34.398348, 132.475657, "22:33", "22:34"),
        ("小倉", 33.887243, 130.883372, "23:25", "23:26"),
        ("博多", 33.589788, 130.421116, "23:42", ""),
    ), "https://timetables.jreast.co.jp/2610/train/175/177271.html", CHECKED_JP),
    PublishedTrain("JR East", "とき 311号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "09:12"),
        ("大宮", 35.906094, 139.623014, "09:33", "09:34"),
        ("新潟", 37.912034, 139.061412, "10:41", ""),
    ), "https://timetables.jreast.co.jp/2610/train/035/038231.html", CHECKED_JP),
    PublishedTrain("JR East", "とき 35号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "15:16"),
        ("上野", 35.713091, 139.7773, "15:21", "15:22"),
        ("大宮", 35.906094, 139.623014, "15:40", "15:41"),
        ("高崎", 36.322766, 139.012994, "16:04", "16:05"),
        ("新潟", 37.912034, 139.061412, "17:03", ""),
    ), "https://timetables.jreast.co.jp/2610/train/125/128191.html", CHECKED_JP),
    PublishedTrain("JR Central / JR West", "のぞみ 201号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "17:21"),
        ("品川", 35.628647, 139.74007, "17:27", "17:28"),
        ("新横浜", 35.507204, 139.617391, "17:38", "17:39"),
        ("名古屋", 35.170581, 136.880978, "18:56", "18:58"),
        ("京都", 34.98461, 135.758451, "19:32", "19:33"),
        ("新大阪", 34.73386, 135.500945, "19:48", "19:50"),
        ("新神戸", 34.706447, 135.195536, "20:02", "20:03"),
        ("岡山", 34.665374, 133.917799, "20:36", "20:37"),
        ("広島", 34.398348, 132.475657, "21:11", "21:12"),
        ("小倉", 33.887243, 130.883372, "21:58", "21:59"),
        ("博多", 33.589788, 130.421116, "22:14", ""),
    ), "https://timetables.jreast.co.jp/2610/train/115/115031.html", CHECKED_JP),
    PublishedTrain("JR East / JR West", "かがやき 519号", "high_speed", (
        ("東京", 35.681051, 139.767397, "", "21:04"),
        ("上野", 35.713091, 139.7773, "21:09", "21:10"),
        ("大宮", 35.906094, 139.623014, "21:28", "21:29"),
        ("長野", 36.642766, 138.188893, "22:23", "22:25"),
        ("富山", 36.701368, 137.213444, "23:10", "23:11"),
        ("金沢", 36.578047, 136.64813, "23:30", ""),
    ), "https://timetables.jreast.co.jp/2610/train/035/038691.html", CHECKED_JP),
    PublishedTrain("JR West / JR Kyushu", "みずほ 601号", "high_speed", (
        ("新大阪", 34.73386, 135.500945, "", "06:00"),
        ("新神戸", 34.706447, 135.195536, "06:12", "06:13"),
        ("岡山", 34.665374, 133.917799, "06:50", "06:51"),
        ("広島", 34.398348, 132.475657, "07:25", "07:26"),
        ("小倉", 33.887243, 130.883372, "08:12", "08:13"),
        ("博多", 33.589788, 130.421116, "08:28", "08:30"),
        ("熊本", 32.790311, 130.688557, "09:02", "09:03"),
        ("鹿児島中央", 31.58365, 130.542218, "09:53", ""),
    ), "https://www.jrkyushu-timetable.jp/sp/2610/0008/00089601.html", CHECKED_JP),
    # ---- Amtrak's Acela; the comment is the days the train runs.
    PublishedTrain("Amtrak", "Acela 2112", "high_speed", (
        ("Washington Union Station", 38.8973, -77.0063, "", "11:55"),
        ("Baltimore Penn Station", 39.3073, -76.6157, "12:27", "12:27"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "13:33", "13:33"),
        ("New York Penn Station", 40.7506, -73.9935, "14:53", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # Mo-Fr
    PublishedTrain("Amtrak", "Acela 2113", "high_speed", (
        ("New York Penn Station", 40.7506, -73.9935, "", "10:00"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "11:10", "11:10"),
        ("Baltimore Penn Station", 39.3073, -76.6157, "12:22", "12:22"),
        ("Washington Union Station", 38.8973, -77.0063, "13:00", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # Mo-Fr
    PublishedTrain("Amtrak", "Acela 2167", "high_speed", (
        ("Boston South Station", 42.3523, -71.0552, "", "13:00"),
        ("Providence", 41.8296, -71.4134, "13:37", "13:37"),
        ("New Haven Union Station", 41.2973, -72.9267, "15:16", "15:16"),
        ("New York Penn Station", 40.7506, -73.9935, "17:00", "17:00"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "18:11", "18:11"),
        ("Washington Union Station", 38.8973, -77.0063, "20:03", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # Mo-Fr
    PublishedTrain("Amtrak", "Acela 2193", "high_speed", (
        ("Boston South Station", 42.3523, -71.0552, "", "18:05"),
        ("Providence", 41.8296, -71.4134, "18:40", "18:40"),
        ("New York Penn Station", 40.7506, -73.9935, "21:46", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # Mo-Fr
    PublishedTrain("Amtrak", "Acela 2250", "high_speed", (
        ("Washington Union Station", 38.8973, -77.0063, "", "08:40"),
        ("Baltimore Penn Station", 39.3073, -76.6157, "09:14", "09:14"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "10:23", "10:23"),
        ("New York Penn Station", 40.7506, -73.9935, "11:58", "11:58"),
        ("Providence", 41.8296, -71.4134, "14:59", "14:59"),
        ("Boston South Station", 42.3523, -71.0552, "15:56", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # SuSa
    PublishedTrain("Amtrak", "Acela 2255", "high_speed", (
        ("Boston South Station", 42.3523, -71.0552, "", "13:10"),
        ("Providence", 41.8296, -71.4134, "13:44", "13:44"),
        ("New Haven Union Station", 41.2973, -72.9267, "15:10", "15:10"),
        ("New York Penn Station", 40.7506, -73.9935, "17:00", "17:00"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "18:13", "18:13"),
        ("Baltimore Penn Station", 39.3073, -76.6157, "19:25", "19:25"),
        ("Washington Union Station", 38.8973, -77.0063, "20:06", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # SuSa
    PublishedTrain("Amtrak", "Acela 2264", "high_speed", (
        ("Washington Union Station", 38.8973, -77.0063, "", "17:55"),
        ("Baltimore Penn Station", 39.3073, -76.6157, "18:29", "18:29"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "19:35", "19:35"),
        ("New York Penn Station", 40.7506, -73.9935, "21:03", "21:03"),
        ("New Haven Union Station", 41.2973, -72.9267, "22:39", "22:39"),
        ("Providence", 41.8296, -71.4134, "00:06", "00:06"),
        ("Boston South Station", 42.3523, -71.0552, "00:49", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # Su
    PublishedTrain("Amtrak", "Acela 2271", "high_speed", (
        ("Boston South Station", 42.3523, -71.0552, "", "06:55"),
        ("Providence", 41.8296, -71.4134, "07:31", "07:31"),
        ("New Haven Union Station", 41.2973, -72.9267, "09:14", "09:14"),
        ("New York Penn Station", 40.7506, -73.9935, "11:06", "11:06"),
        ("Philadelphia 30th Street Station", 39.9556, -75.182, "12:21", "12:21"),
        ("Baltimore Penn Station", 39.3073, -76.6157, "13:26", "13:26"),
        ("Washington Union Station", 38.8973, -77.0063, "14:01", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # Mo-Fr
    PublishedTrain("Amtrak", "Acela 2293", "high_speed", (
        ("Boston South Station", 42.3523, -71.0552, "", "18:15"),
        ("Providence", 41.8296, -71.4134, "18:52", "18:52"),
        ("New Haven Union Station", 41.2973, -72.9267, "20:32", "20:32"),
        ("New York Penn Station", 40.7506, -73.9935, "22:06", ""),
    ), AMTRAK_SOURCE, CHECKED_US),   # SuSa
    # ---- China Railway: each corridor's fastest direct train on 2026-10-22.
    # 北京南-上海虹桥: fastest of 54 trains, 258 min (17:00-21:18)
    PublishedTrain("China Railway", "G25", "high_speed", (
        ("北京南", 39.863483, 116.372399, "", "17:00"),
        ("南京南", 31.970797, 118.793052, "20:14", "20:16"),
        ("上海虹桥", 31.195978, 121.3162, "21:18", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 北京西-广州南 (13 trains), 北京西-深圳北 (8) and 北京西-香港西九龙 (1):
    # 437, 470 and 492 min; runs 北京西 - 香港西九龙
    PublishedTrain("China Railway", "G381", "high_speed", (
        ("北京西", 39.893652, 116.315221, "", "10:00"),
        ("石家庄", 38.009503, 114.478129, "11:00", "11:02"),
        ("郑州东", 34.760194, 113.773253, "12:18", "12:21"),
        ("武汉", 30.60985, 114.418943, "13:55", "13:59"),
        ("长沙南", 28.150078, 113.059881, "15:10", "15:13"),
        ("广州南", 22.991414, 113.264038, "17:17", "17:21"),
        ("深圳北", 22.612036, 114.023947, "17:50", "17:54"),
        ("香港西九龙", 22.303681, 114.164927, "18:12", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-广州南: fastest of 23 trains, 387 min (16:00-22:27)
    PublishedTrain("China Railway", "G253", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "16:00"),
        ("杭州东", 30.293549, 120.208203, "16:45", "16:49"),
        ("南昌西", 28.625729, 115.787711, "18:56", "19:00"),
        ("长沙南", 28.150078, 113.059881, "20:19", "20:23"),
        ("广州南", 22.991414, 113.264038, "22:27", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-深圳北: fastest of 18 trains, 395 min (15:00-21:35)
    PublishedTrain("China Railway", "G269", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "15:00"),
        ("杭州东", 30.293549, 120.208203, "15:45", "15:48"),
        ("深圳北", 22.612036, 114.023947, "21:35", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-成都东: fastest of 18 trains, 631 min (09:04-19:35)
    PublishedTrain("China Railway", "G237", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "09:04"),
        ("杭州东", 30.293549, 120.208203, "09:49", "09:53"),
        ("南昌西", 28.625729, 115.787711, "12:00", "12:03"),
        ("长沙南", 28.150078, 113.059881, "13:22", "13:26"),
        ("成都东", 30.631298, 104.138921, "19:35", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-重庆北: fastest of 26 trains, 593 min (07:04-16:57); runs on
    # to 成都南
    PublishedTrain("China Railway", "G3390", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "07:04"),
        ("南京南", 31.970797, 118.793052, "09:11", "09:23"),
        ("合肥南", 31.800299, 117.284875, "10:17", "10:21"),
        ("汉口", 30.621651, 114.249414, "12:20", "12:32"),
        ("重庆北", 29.612322, 106.547273, "16:57", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 北京西-西安北: fastest of 41 trains, 250 min (07:55-12:05); runs on to 兰州西
    PublishedTrain("China Railway", "G351", "high_speed", (
        ("北京西", 39.893652, 116.315221, "", "07:55"),
        ("石家庄", 38.009503, 114.478129, "08:56", "08:58"),
        ("郑州东", 34.760194, 113.773253, "10:14", "10:18"),
        ("西安北", 34.377668, 108.934025, "12:05", "12:10"),
        ("兰州西", 36.067584, 103.749284, "14:38", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 西安北-成都东: fastest of 88 trains, 185 min (11:25-14:30)
    PublishedTrain("China Railway", "G321", "high_speed", (
        ("北京西", 39.893652, 116.315221, "", "07:00"),
        ("石家庄", 38.009503, 114.478129, "08:01", "08:03"),
        ("郑州东", 34.760194, 113.773253, "09:21", "09:24"),
        ("西安北", 34.377668, 108.934025, "11:20", "11:25"),
        ("成都东", 30.631298, 104.138921, "14:30", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 北京朝阳-哈尔滨西: fastest of 41 trains, 273 min (08:00-12:33)
    PublishedTrain("China Railway", "G101", "high_speed", (
        ("北京朝阳", 39.943316, 116.502418, "", "08:00"),
        ("沈阳北", 41.817335, 123.429435, "10:29", "10:32"),
        ("长春西", 43.874938, 125.193904, "11:36", "11:38"),
        ("哈尔滨西", 45.705144, 126.572324, "12:33", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 北京南-福州: fastest of 12 trains, 471 min (06:56-14:47)
    PublishedTrain("China Railway", "G87", "high_speed", (
        ("北京南", 39.863483, 116.372399, "", "06:56"),
        ("天津南", 39.056049, 117.054501, "07:27", "07:29"),
        ("济南西", 36.668804, 116.886004, "08:27", "08:30"),
        ("徐州东", 34.269163, 117.300205, "09:27", "09:29"),
        ("合肥南", 31.800299, 117.284875, "10:54", "10:59"),
        ("福州", 26.116809, 119.315632, "14:47", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-昆明南: fastest of 6 trains, 575 min (10:00-19:35)
    PublishedTrain("China Railway", "G201", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "10:00"),
        ("杭州东", 30.293549, 120.208203, "10:45", "10:50"),
        ("南昌西", 28.625729, 115.787711, "12:50", "12:53"),
        ("长沙南", 28.150078, 113.059881, "14:06", "14:10"),
        ("贵阳北", 26.622834, 106.672454, "17:05", "17:10"),
        ("昆明南", 24.873363, 102.86038, "19:35", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 广州南-昆明南: fastest of 29 trains, 400 min (12:12-18:52); from 香港西九龙
    PublishedTrain("China Railway", "G908", "high_speed", (
        ("香港西九龙", 22.303681, 114.164927, "", "11:14"),
        ("深圳北", 22.612036, 114.023947, "11:32", "11:37"),
        ("广州南", 22.991414, 113.264038, "12:06", "12:12"),
        ("贵阳北", 26.622834, 106.672454, "16:15", "16:25"),
        ("昆明南", 24.873363, 102.86038, "18:52", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 北京西-武汉: fastest of 63 trains, 228 min (09:05-12:53)
    PublishedTrain("China Railway", "G339", "high_speed", (
        ("北京西", 39.893652, 116.315221, "", "09:05"),
        ("郑州东", 34.760194, 113.773253, "11:16", "11:19"),
        ("武汉", 30.60985, 114.418943, "12:53", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-武汉: fastest of 61 trains, 212 min (16:53-20:25)
    PublishedTrain("China Railway", "G460", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "16:53"),
        ("南京南", 31.970797, 118.793052, "17:56", "17:58"),
        ("合肥南", 31.800299, 117.284875, "18:46", "18:48"),
        ("武汉", 30.60985, 114.418943, "20:25", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 广州南-香港西九龙: fastest of 62 trains, 47 min (10:14-11:01)
    PublishedTrain("China Railway", "G6503", "high_speed", (
        ("广州南", 22.991414, 113.264038, "", "10:14"),
        ("香港西九龙", 22.303681, 114.164927, "11:01", ""),
    ), CR_SOURCE, CHECKED_CN),
    # 上海虹桥-西安北: fastest of 37 trains, 339 min (08:55-14:34)
    PublishedTrain("China Railway", "G94", "high_speed", (
        ("上海虹桥", 31.195978, 121.3162, "", "08:55"),
        ("南京南", 31.970797, 118.793052, "09:54", "09:56"),
        ("徐州东", 34.269163, 117.300205, "11:02", "11:06"),
        ("郑州东", 34.760194, 113.773253, "12:37", "12:40"),
        ("西安北", 34.377668, 108.934025, "14:34", ""),
    ), CR_SOURCE, CHECKED_CN),
)


def _clock(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def call_minutes(train: PublishedTrain) -> list[tuple[float, float]]:
    """(arrival, departure) of each call in minutes from the first
    departure's midnight, running on past 24:00 where the train does."""
    out: list[tuple[float, float]] = []
    day = last = 0
    for _name, _lat, _lon, arr, dep in train.calls:
        a = _clock(arr or dep) + day
        if a < last:                      # the clock passed midnight
            day += 1440
            a += 1440
        d = _clock(dep or arr) + day
        if d < a:
            day += 1440
            d += 1440
        out.append((float(a), float(d)))
        last = d
    return out


def rows(trains: tuple[PublishedTrain, ...] | None = None) -> pl.DataFrame:
    """Every pair of each train's calls (TRAINS by default) as a two-stop
    route, in `gtfs_rail.timetable_rows`' frame: `timetabled_min`
    departure(i) -> arrival(j) on the boarding row, the alighting row
    `alight_only`."""
    out = []
    for t in TRAINS if trains is None else trains:
        times = call_minutes(t)
        for i in range(len(t.calls)):
            for j in range(i + 1, len(t.calls)):
                minutes = times[j][0] - times[i][1]
                key = f"published|{t.operator}|{t.train}|{i}|{j}".encode()
                rid = -(int.from_bytes(hashlib.sha1(key).digest()[:6], "big") + 1)
                for seq, k in enumerate((i, j)):
                    name, lat, lon, _a, _d = t.calls[k]
                    out.append({"route_id": rid, "seq": seq, "stop_id": rid * 2 - seq,
                                "lat": lat, "lon": lon, "name": name, "tier": t.tier,
                                "route_name": t.train, "operator": t.operator, "ref": "",
                                "stops_listed": 2,
                                "timetabled_min": minutes if seq == 0 else None,
                                "alight_only": seq == 1, "feed": "published"})
    return pl.DataFrame(out, schema={
        "route_id": pl.Int64, "seq": pl.Int64, "stop_id": pl.Int64, "lat": pl.Float64,
        "lon": pl.Float64, "name": pl.Utf8, "tier": pl.Utf8, "route_name": pl.Utf8,
        "operator": pl.Utf8, "ref": pl.Utf8, "stops_listed": pl.Int64,
        "timetabled_min": pl.Float64, "alight_only": pl.Boolean, "feed": pl.Utf8})
