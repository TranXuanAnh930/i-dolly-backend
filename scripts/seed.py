"""Seed script — populates the database with realistic test data for local
development: three fictional management companies, five idol groups plus
three solo idols (all Japanese, spanning J-Pop, city pop, an anime tie-in
act, a gothic idol unit, and a vocaloid-adjacent digital unit), venues and
concerts across Japan, ticket types (priced in yen), a 20-item
album/single/EP/lightstick/merch lineup (also priced in yen), and a slice of
the lottery flow (preferences + entries) plus one manually-issued ticket.
Every name here is invented for testing, not a real artist, group, or
company.

Idol portraits and product covers are seeded from tests/fixtures/ — see that
folder's README for how they were generated (procedural placeholder art, not
real character art: no AI image-generation tool was available in the
environment this project was built in). Each is pushed through the same
get_storage().save() coroutine app/router/idol.py and app/router/products.py
call on a real upload, via the tiny UploadFile duck-type below, so the seed
data exercises the real storage abstraction end to end rather than writing
image_url strings directly.

Idempotent: checks for a sentinel row ("Nova Entertainment") before doing
anything, so re-running it after the data already exists is a no-op instead
of crashing on a unique-constraint violation. Categories are get-or-created
(never seeded by a migration); idol_colors/positions/genres are looked up by
name — seeded by migrations (see alembic/versions/46c5f500e7bd_*,
ecf1f2ed802f_*, 44ccae8cac48_*, and 10f9dfa05636_extend_idol_colors_and_genres.py
for the roster this file now needs). This script never deletes anything.

Lives in scripts/, not the repo root — run from the repo root (paths below
are resolved relative to this file's location either way, not the current
working directory) inside the app container (after `alembic upgrade head`
has succeeded):
    docker compose exec app python scripts/seed.py

If the app container isn't up yet, this starts a temporary one just for the
seed run:
    docker compose run --rm app python scripts/seed.py

All seeded user accounts share the password: Password123!
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# This file lives in scripts/, one level below the repo root where the `app`
# package actually is — insert the repo root at the front of sys.path so
# `from app...` below resolves regardless of how this script is invoked
# (`python scripts/seed.py` from any cwd, not just `python -m scripts.seed`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importing from app.db.base (not the individual model modules) so every
# model in the app is registered before SQLAlchemy configures its mappers —
# see the CORRECTION comment in app/db/base.py. Hand-picking only the models
# this script touches (the original approach here) crashed with
# "InvalidRequestError: ... failed to locate a name ('Cart')" the moment
# mapper configuration ran, because Users.cart's string-based relationship()
# pointed at a class this script never imported.
from app.db.base import (
    AlbumDetail,
    AlbumGenre,
    Category,
    Concert,
    ConcertPerformer,
    DirectSaleCampaign,
    Genre,
    Group,
    Idol,
    IdolColor,
    IdolPosition,
    LotteryCampaign,
    LotteryEntry,
    LotteryPreference,
    ManagementCompany,
    MerchDetail,
    Position,
    Product,
    Ticket,
    TicketType,
    Users,
    Venue,
)
from app.db.session import session as SessionLocal
from app.utils.hashing import hash_password
from app.utils.storage import get_storage

SEED_PASSWORD = "Password123!"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


# --- fixture image upload (real storage abstraction, not a shortcut) -------

class _FixtureUploadFile:
    """Minimal UploadFile duck-type: StorageBackend.save() only ever touches
    .content_type, .filename, and an async .read(size) — so this is enough
    to push a local fixture file through get_storage().save() exactly like
    a real multipart upload would, without needing a running request or an
    ASGI-provided UploadFile (and without pinning this script to whatever
    starlette version happens to be installed)."""

    def __init__(self, path: Path, content_type: str = "image/png"):
        self._f = open(path, "rb")
        self.filename = path.name
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        return self._f.read(size)

    def close(self):
        self._f.close()


def upload_fixture(filename: str, subfolder: str) -> str:
    """Synchronous wrapper: this is a plain script, not an ASGI app, so
    there's no event loop already running — asyncio.run() per call is fine
    here (it would NOT be inside a real request handler)."""
    path = FIXTURES_DIR / subfolder / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing fixture image: {path} — run tests/fixtures' generation "
            f"script, or check the filename matches what it wrote."
        )

    async def _do():
        upload = _FixtureUploadFile(path)
        try:
            return await get_storage().save(upload, subfolder)
        finally:
            upload.close()

    return asyncio.run(_do())


def color_id(db, name):
    row = db.query(IdolColor).filter(IdolColor.name == name).one()
    return row.id


def position_id(db, name):
    row = db.query(Position).filter(Position.name == name).one()
    return row.id


def genre_id(db, name):
    row = db.query(Genre).filter(Genre.name == name).one()
    return row.id


def get_or_create_category(db, name, is_resale_capped):
    row = db.query(Category).filter(Category.name == name).first()
    if row:
        return row
    row = Category(name=name, is_resale_capped=is_resale_capped)
    db.add(row)
    db.flush()
    return row


def seed_ready_to_draw_lottery(db, concert, tt_vip, tt_premium, tt_regular, group_a, group_b, group_c):
    """3 lottery campaigns (vip/premium/regular) whose entry window has
    already closed — immediately drawable via PUT /concerts/lottery-draw/
    {id}, no need to wait or fudge a campaign's entry_end_at first. Same
    "rank-1 crowd, some fall through to rank 2" cascade shape as the
    original concert_countdown data this was factored out of: group_a
    ranks vip=1/premium=2, group_b ranks premium=1/regular=2, group_c ranks
    regular=1 only — see the original block's comment (git history) for
    exactly which rank-cascade case each transition exercises. Reusable so
    every company gets at least one concert its own manager can draw
    against, not just Nova's."""
    now = datetime.now(timezone.utc)
    campaign_vip = LotteryCampaign(
        ticket_type_id=tt_vip.id,
        entry_start_at=now - timedelta(days=20), entry_end_at=now - timedelta(days=1),
        status="open",  # draw_at stays NULL until PUT /concerts/lottery-draw/{id} actually runs
    )
    campaign_premium = LotteryCampaign(
        ticket_type_id=tt_premium.id,
        entry_start_at=now - timedelta(days=20), entry_end_at=now - timedelta(days=1),
        status="open",
    )
    campaign_regular = LotteryCampaign(
        ticket_type_id=tt_regular.id,
        entry_start_at=now - timedelta(days=20), entry_end_at=now - timedelta(days=1),
        status="open",
    )
    db.add_all([campaign_vip, campaign_premium, campaign_regular])
    db.flush()

    preferences = []
    for fan in group_a:
        preferences.append(LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tt_vip.id, rank=1))
        preferences.append(LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tt_premium.id, rank=2))
    for fan in group_b:
        preferences.append(LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tt_premium.id, rank=1))
        preferences.append(LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tt_regular.id, rank=2))
    for fan in group_c:
        preferences.append(LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tt_regular.id, rank=1))
    db.add_all(preferences)
    db.flush()

    entries = []
    for fan in group_a:
        entries.append(LotteryEntry(campaign_id=campaign_vip.id, user_id=fan.id))
        entries.append(LotteryEntry(campaign_id=campaign_premium.id, user_id=fan.id))
    for fan in group_b:
        entries.append(LotteryEntry(campaign_id=campaign_premium.id, user_id=fan.id))
        entries.append(LotteryEntry(campaign_id=campaign_regular.id, user_id=fan.id))
    for fan in group_c:
        entries.append(LotteryEntry(campaign_id=campaign_regular.id, user_id=fan.id))
    db.add_all(entries)
    db.flush()


def seed(db):
    now = datetime.now(timezone.utc)

    # --- management companies -------------------------------------------
    nova = ManagementCompany(
        name="Nova Entertainment",
        description="Tokyo-based label built on glossy, radio-ready J-Pop and a laid-back city-pop revival act.",
        contact_email="contact@nova-entertainment.example",
    )
    starlight = ManagementCompany(
        name="Starlight Media",
        description="Anime-adjacent idol powerhouse pairing chart hits with elaborate stage concepts and tie-in soundtracks.",
        contact_email="contact@starlight-media.example",
    )
    kuroyuri = ManagementCompany(
        name="Kuroyuri Records",
        description="Alt-idol label leaning into gothic aesthetics and vocal-synth-adjacent production credits.",
        contact_email="contact@kuroyuri-records.example",
    )
    db.add_all([nova, starlight, kuroyuri])
    db.flush()

    # --- users -------------------------------------------------------------
    admin = Users(
        name="Admin",
        email="admin@example.com",
        hashed_password=hash_password(SEED_PASSWORD),
        role="admin",
        is_active=True,
        is_verified=True,
    )
    manager_nova = Users(
        name="Naomi Segawa",
        email="manager.nova@example.com",
        hashed_password=hash_password(SEED_PASSWORD),
        role="manager",
        company_id=nova.id,
        is_active=True,
        is_verified=True,
    )
    manager_starlight = Users(
        name="Kenji Arakawa",
        email="manager.starlight@example.com",
        hashed_password=hash_password(SEED_PASSWORD),
        role="manager",
        company_id=starlight.id,
        is_active=True,
        is_verified=True,
    )
    manager_kuroyuri = Users(
        name="Yuria Kagami",
        email="manager.kuroyuri@example.com",
        hashed_password=hash_password(SEED_PASSWORD),
        role="manager",
        company_id=kuroyuri.id,
        is_active=True,
        is_verified=True,
    )
    fan_alex = Users(
        name="Alex Chen", email="alex.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_priya = Users(
        name="Priya Nair", email="priya.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_marco = Users(
        name="Marco Silva", email="marco.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_yuki = Users(
        name="Yuki Tanaka", email="yuki.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    # Eight more fans, on top of the four above — a bigger applicant pool so
    # the lottery draw endpoint has real competition to draw against (see
    # the "lottery: preferences, campaigns, entries" section below).
    fan_sofia = Users(
        name="Sofia Rossi", email="sofia.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_liam = Users(
        name="Liam O'Connor", email="liam.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_haruto = Users(
        name="Haruto Mizushima", email="haruto.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_emma = Users(
        name="Emma Larsson", email="emma.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_noah = Users(
        name="Noah Kim", email="noah.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_aiko = Users(
        name="Aiko Fujiwara", email="aiko.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_diego = Users(
        name="Diego Fernandez", email="diego.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    fan_chloe = Users(
        name="Chloe Dubois", email="chloe.fan@example.com",
        hashed_password=hash_password(SEED_PASSWORD), role="fan",
        is_active=True, is_verified=True,
    )
    db.add_all([
        admin, manager_nova, manager_starlight, manager_kuroyuri,
        fan_alex, fan_priya, fan_marco, fan_yuki,
        fan_sofia, fan_liam, fan_haruto, fan_emma, fan_noah, fan_aiko, fan_diego, fan_chloe,
    ])
    db.flush()

    # --- groups --------------------------------------------------------
    sakura_prism = Group(
        company_id=nova.id, name="Sakura Prism",
        debut_date=date(2022, 4, 8),
        description="A 5-member idol-pop unit built on glossy hooks, precise formations, and a permanently upbeat stage persona.",
    )
    nagisa_melody = Group(
        company_id=nova.id, name="Nagisa Melody",
        debut_date=date(2021, 6, 21),
        description="A 4-member city-pop revival band-idol hybrid — real instruments, sun-faded harmonies, deliberately unhurried.",
    )
    kessho_stars = Group(
        company_id=starlight.id, name="Kessho Stars",
        debut_date=date(2023, 1, 14),
        description="A 5-member anime tie-in idol unit whose discography doubles as opening/ending themes for a shared in-universe magical-girl franchise.",
    )
    yozora_requiem = Group(
        company_id=kuroyuri.id, name="Yozora Requiem",
        debut_date=date(2020, 10, 31),
        description="A 4-member gothic idol unit — minor-key ballads, near-dark staging, deliberately unsmiling promo photos.",
    )
    program_heart = Group(
        company_id=kuroyuri.id, name="Program:HEART",
        debut_date=date(2022, 11, 3),
        description="A 4-member vocal-synth-adjacent digital idol unit, led by a member who still mixes every track herself.",
    )
    db.add_all([sakura_prism, nagisa_melody, kessho_stars, yozora_requiem, program_heart])
    db.flush()

    # --- idols -----------------------------------------------------------
    # (name, company, group, color, dob, hometown, short_intro, personality, positions[primary first])
    idols = [
        ("Hinata Kisaragi", nova, sakura_prism, "Cotton Candy Pink", date(1999, 4, 12), "Yokohama, Japan",
         "Leader and main vocalist of Sakura Prism.",
         "Relentlessly upbeat team mom who apologizes to the practice-room mirror before every run-through and remembers every fan's name after one meeting.",
         ["Leader", "Main Vocalist"]),
        ("Momoka Serizawa", nova, sakura_prism, "Peach Sorbet", date(2000, 8, 22), "Tokyo, Japan",
         "Center and lead dancer of Sakura Prism.",
         "Competitive perfectionist who reviews her own choreography frame-by-frame and has never once called a routine 'good enough.'",
         ["Center", "Lead Dancer"]),
        ("Yui Amamiya", nova, sakura_prism, "Butter Yellow", date(2001, 11, 3), "Kyoto, Japan",
         "Vocalist for Sakura Prism.",
         "Perpetually sleepy off-stage, but the instant a mic goes live she's the group's secret power vocalist — nobody's figured out how she does it.",
         ["Vocalist"]),
        ("Riko Fujimori", nova, sakura_prism, "Tangerine Pop", date(2003, 2, 17), "Osaka, Japan",
         "Rapper for Sakura Prism.",
         "Talks entirely in rhythm-game metaphors and treats every fan meet like a boss fight she's determined to S-rank.",
         ["Rapper"]),
        ("Nozomi Aizawa", nova, sakura_prism, "Sakura Blossom", date(2005, 5, 30), "Sapporo, Japan",
         "Maknae and visual of Sakura Prism.",
         "Youngest member with an old soul — collects vintage cassette tapes and gently corrects the staff's honorifics.",
         ["Maknae", "Visual"]),

        ("Sora Minase", nova, nagisa_melody, "Sky Mint", date(1998, 6, 9), "Fukuoka, Japan",
         "Leader and guitarist of Nagisa Melody.",
         "Surf-rock devotee convinced every song secretly wants a beach-sunset bridge — and usually wins that argument in the writing room.",
         ["Leader", "Guitarist"]),
        ("Ao Tachibana", nova, nagisa_melody, "Baby Blue", date(1999, 12, 25), "Kobe, Japan",
         "Bassist and vocalist of Nagisa Melody.",
         "Deadpan comedian whose entire stage banter is dry one-liners delivered without a single facial muscle moving.",
         ["Bassist", "Vocalist"]),
        ("Nagi Hoshikawa", nova, nagisa_melody, "Mint Cream", date(2000, 3, 14), "Nagoya, Japan",
         "Keyboardist of Nagisa Melody.",
         "Composes lo-fi remixes of the group's own songs at 3am and uploads them anonymously under a badly-kept-secret alias.",
         ["Keyboardist"]),
        ("Kanade Umino", nova, nagisa_melody, "Lilac Bloom", date(2002, 9, 8), "Naha, Japan",
         "Drummer and maknae of Nagisa Melody.",
         "Former competitive swimmer who treats every drum fill like a relay handoff — precise, breathless, never late.",
         ["Drummer", "Maknae"]),

        ("Akira Hoshimiya", starlight, kessho_stars, "Periwinkle Pop", date(1999, 1, 5), "Chiba, Japan",
         "Leader and main vocalist of Kessho Stars.",
         "Speaks entirely in shonen-protagonist declarations and genuinely believes every concert is the group's 'final battle' — somehow it works.",
         ["Leader", "Main Vocalist"]),
        ("Ren Kazahaya", starlight, kessho_stars, "Golden Hour", date(2000, 7, 19), "Tokyo, Japan",
         "Lead dancer and visual of Kessho Stars.",
         "Auditioned for a magical-girl anime role, didn't get the part, got asked to sing the character's theme song instead — has performed in a stage cape ever since, 'for the bit.'",
         ["Lead Dancer", "Visual"]),
        ("Towa Kirishima", starlight, kessho_stars, "Amber Glow", date(2001, 10, 2), "Sendai, Japan",
         "Rapper for Kessho Stars.",
         "Writes fight-scene choreography notes in the margins of the group's rap verses and insists every bridge needs a 'power-up moment.'",
         ["Rapper"]),
        ("Hikaru Otonashi", starlight, kessho_stars, "Neon Cyan", date(2002, 4, 27), "Yokohama, Japan",
         "Vocalist for Kessho Stars.",
         "Voice-actor-understudy energy — can recite the group's entire anime tie-in dialogue from memory, in character, unprompted.",
         ["Vocalist"]),
        ("Yuzuki Amagi", starlight, kessho_stars, "Bubblegum Purple", date(2004, 12, 11), "Hiroshima, Japan",
         "Maknae and dancer of Kessho Stars.",
         "Treats every stage like a convention-hall panel — waves at specific fans by their cosplay from previous shows.",
         ["Maknae", "Dancer"]),

        ("Aoi Kurenai", kuroyuri, yozora_requiem, "Onyx Black", date(1998, 10, 31), "Tokyo, Japan",
         "Leader and main vocalist of Yozora Requiem.",
         "Speaks softly, writes uncompromisingly bleak lyrics, and insists on rehearsing in near-darkness 'for the atmosphere.'",
         ["Leader", "Main Vocalist"]),
        ("Suzune Yamikawa", kuroyuri, yozora_requiem, "Blood Rose", date(1999, 6, 13), "Yokohama, Japan",
         "Vocalist for Yozora Requiem.",
         "Trained in classical opera before going full alt-idol — can hit an aria mid-verse and does, whether the arrangement asks for it or not.",
         ["Vocalist"]),
        ("Karen Shirayuki", kuroyuri, yozora_requiem, "Plum Wine", date(2001, 2, 8), "Sapporo, Japan",
         "Dancer and visual of Yozora Requiem.",
         "Choreographs like she's haunting the stage rather than performing on it — deliberately never smiles in promo photos.",
         ["Dancer", "Visual"]),
        ("Mizuki Tsukishiro", kuroyuri, yozora_requiem, "Deep Indigo", date(2003, 9, 21), "Nagasaki, Japan",
         "Maknae and vocalist of Yozora Requiem.",
         "Writes horror short stories between rehearsals and workshops the group's stage concepts like campfire ghost stories.",
         ["Maknae", "Vocalist"]),

        ("Mira Kanade", kuroyuri, program_heart, "Synth Teal", date(2000, 5, 5), "Tokyo, Japan",
         "Leader and producer of Program:HEART.",
         "Started as a bedroom vocal-synth producer, still mixes the group's own tracks at 4am, and refuses to let anyone else touch the DAW.",
         ["Leader", "Producer"]),
        ("Rio Kirisame", kuroyuri, program_heart, "Moonlight Silver", date(2001, 8, 16), "Yokohama, Japan",
         "Vocalist for Program:HEART.",
         "Speaks in a flat, deliberately synth-adjacent cadence on stage and completely normally off it — nobody agrees on whether it's a bit.",
         ["Vocalist"]),
        ("Nana Shirakawa", kuroyuri, program_heart, "Ghost Lavender", date(2002, 1, 29), "Osaka, Japan",
         "Dancer for Program:HEART.",
         "Learns choreography by watching it once at half-speed and never needs to see it again — the group's uncanny fast study.",
         ["Dancer"]),
        ("Kohaku Amemiya", kuroyuri, program_heart, "Pastel Aqua", date(2004, 11, 7), "Kyoto, Japan",
         "Maknae and vocalist of Program:HEART.",
         "Insists on a glitch sound effect before every one of her solo lines and has never once let a producer cut it.",
         ["Maknae", "Vocalist"]),

        ("Rin Amane", nova, None, "Ivory Frost", date(1997, 3, 2), "Yokosuka, Japan",
         "Soloist known for cinematic R&B.",
         "Writes every lyric by hand in a paper notebook before typing it, and refuses to release a song until she's cried during at least one demo take.",
         ["Vocalist"]),
        ("Kaede Shirogane", starlight, None, "Crimson Ember", date(1998, 9, 14), "Tokyo, Japan",
         "Anime insert-song specialist.",
         "Auditioned for an anime heroine role, didn't get cast, got asked to sing the character's theme instead — has performed exclusively in a stage cape ever since.",
         ["Vocalist"]),
        ("Yoru Kuon", kuroyuri, None, "Twilight Rose", date(1996, 12, 20), "Sapporo, Japan",
         "Vocal-synth producer turned soloist.",
         "Former faceless vocal-synth producer who stepped into the spotlight reluctantly — still performs behind a translucent screen for the first verse of every show.",
         ["Producer", "Vocalist"]),
    ]

    idol_rows = {}
    for name, company, group, color_name, dob, hometown, intro, personality, positions in idols:
        image_url = upload_fixture(f"{_slug(name)}.png", "idols")
        row = Idol(
            company_id=company.id,
            group_id=group.id if group else None,
            name=name,
            date_of_birth=dob,
            hometown=hometown,
            color_id=color_id(db, color_name),
            short_intro=intro,
            long_description=personality,
            profile_image_url=image_url,
        )
        db.add(row)
        db.flush()
        idol_rows[name] = row
        for i, pos_name in enumerate(positions):
            db.add(IdolPosition(idol_id=row.id, position_id=position_id(db, pos_name), is_primary=(i == 0)))
    db.flush()

    # --- venues (all Japan) ------------------------------------------------
    grove_hall = Venue(name="The Grove Hall", address="2-14 Daimyo, Chuo-ku", city="Fukuoka",
                        country="Japan", total_capacity=8000, contact_info="events@grovehall.example")
    skyline_arena = Venue(name="Skyline Arena", address="1-1 Nakama, Naka-ku", city="Nagoya",
                           country="Japan", total_capacity=15000, contact_info="booking@skylinearena.example")
    harbor_point = Venue(name="Harbor Point Amphitheater", address="1-1 Minato Mirai, Nishi-ku", city="Yokohama",
                          country="Japan", total_capacity=35000, contact_info="events@harborpoint.example")
    riverside_stadium = Venue(name="Riverside Stadium", address="8 Shintoshin, Chuo-ku", city="Saitama",
                               country="Japan", total_capacity=55000, contact_info="booking@riversidestadium.example")
    crescent_hall = Venue(name="Crescent Hall", address="5-1 Crescent Ave", city="Tokyo",
                           country="Japan", total_capacity=12000, contact_info="events@crescenthall.example")
    starlight_dome = Venue(name="Starlight Dome", address="3-2 Namba Blvd", city="Osaka",
                            country="Japan", total_capacity=30000, contact_info="booking@starlightdome.example")
    db.add_all([grove_hall, skyline_arena, harbor_point, riverside_stadium, crescent_hall, starlight_dome])
    db.flush()

    # --- concerts & performers --------------------------------------------
    concert_sakura = Concert(
        company_id=nova.id, venue_id=crescent_hall.id,
        title="Sakura Prism: Hanabi Ranman Tour - Tokyo",
        description="Sakura Prism's hometown stop on the Hanabi Ranman Tour.",
        capacity=11000, event_datetime=now + timedelta(days=30),
        doors_open_at=now + timedelta(days=30, hours=-1), status="on_sale",
    )
    concert_nagisa = Concert(
        company_id=nova.id, venue_id=grove_hall.id,
        title="Nagisa Melody: Midnight Drive Live",
        description="An intimate city-pop night with Nagisa Melody's full backing band.",
        capacity=7000, event_datetime=now + timedelta(days=20),
        doors_open_at=now + timedelta(days=20, hours=-1), status="on_sale",
    )
    concert_kessho = Concert(
        company_id=starlight.id, venue_id=starlight_dome.id,
        title="Kessho Stars: Starlight Oath Tour - Osaka",
        description="Kessho Stars' arena show built around their anime tie-in discography.",
        capacity=28000, event_datetime=now + timedelta(days=45),
        doors_open_at=now + timedelta(days=45, hours=-1), status="scheduled",
    )
    concert_yozora = Concert(
        company_id=kuroyuri.id, venue_id=harbor_point.id,
        title="Yozora Requiem: Requiem for Dawn",
        description="Yozora Requiem's gothic amphitheater performance, staged almost entirely in shadow.",
        capacity=32000, event_datetime=now + timedelta(days=50),
        doors_open_at=now + timedelta(days=50, hours=-1), status="scheduled",
    )
    concert_program = Concert(
        company_id=kuroyuri.id, venue_id=skyline_arena.id,
        title="Program:HEART: Recompile Live",
        description="Program:HEART's vocal-synth-driven arena debut.",
        capacity=13500, event_datetime=now + timedelta(days=35),
        doors_open_at=now + timedelta(days=35, hours=-1), status="on_sale",
    )
    concert_solo_showcase = Concert(
        company_id=nova.id, venue_id=riverside_stadium.id,
        title="Nova x Kuroyuri Solo Showcase",
        description="A joint label showcase featuring solo acts Rin Amane, Kaede Shirogane, and Yoru Kuon.",
        capacity=50000, event_datetime=now + timedelta(days=15),
        doors_open_at=now + timedelta(days=15, hours=-1), status="on_sale",
    )
    # A concert dedicated to exercising the lottery draw end to end: three
    # lottery tiers (vip/premium/regular — the first seeded use of
    # "premium," everything else so far only ever used vip/regular), a
    # small enough capacity per tier that 12 applicants produces real
    # competition, and an entry_end_at already in the past so its campaigns
    # are immediately drawable (see the lottery section below) rather than
    # rejected with "campaign_not_ended" the way concert_sakura's/
    # concert_kessho's existing campaigns still are (their entry windows
    # are deliberately still open, for testing the apply/preference flow).
    concert_countdown = Concert(
        company_id=nova.id, venue_id=crescent_hall.id,
        title="Sakura Prism: New Year Countdown Live",
        description="A New Year's Eve countdown show — Sakura Prism's biggest lottery draw of the year.",
        capacity=11000, event_datetime=now + timedelta(days=25),
        doors_open_at=now + timedelta(days=25, hours=-1), status="on_sale",
    )
    # Two more "ready to draw" concerts, one per remaining company — Nova's
    # own manager already has concert_countdown above; without these,
    # manager_starlight/manager_kuroyuri have nothing they can actually
    # draw, which is exactly the gap that would leave the company-scoped
    # RBAC check on PUT /concerts/lottery-draw/{id} (see project_status.md's
    # fixed lottery-draw RBAC bug) untested for two of the three companies.
    concert_kessho_finale = Concert(
        company_id=starlight.id, venue_id=starlight_dome.id,
        title="Kessho Stars: Eternal Oath Finale",
        description="Kessho Stars' season finale — the anime tie-in franchise's climactic concert arc.",
        capacity=28000, event_datetime=now + timedelta(days=40),
        doors_open_at=now + timedelta(days=40, hours=-1), status="on_sale",
    )
    concert_program_closing = Concert(
        company_id=kuroyuri.id, venue_id=skyline_arena.id,
        title="Program:HEART: System Shutdown Finale",
        description="Program:HEART's closing show for the Recompile era.",
        capacity=13500, event_datetime=now + timedelta(days=42),
        doors_open_at=now + timedelta(days=42, hours=-1), status="on_sale",
    )
    db.add_all([
        concert_sakura, concert_nagisa, concert_kessho,
        concert_yozora, concert_program, concert_solo_showcase, concert_countdown,
        concert_kessho_finale, concert_program_closing,
    ])
    db.flush()

    db.add_all([
        ConcertPerformer(concert_id=concert_sakura.id, group_id=sakura_prism.id),
        ConcertPerformer(concert_id=concert_nagisa.id, group_id=nagisa_melody.id),
        ConcertPerformer(concert_id=concert_kessho.id, group_id=kessho_stars.id),
        ConcertPerformer(concert_id=concert_yozora.id, group_id=yozora_requiem.id),
        ConcertPerformer(concert_id=concert_program.id, group_id=program_heart.id),
        ConcertPerformer(concert_id=concert_solo_showcase.id, idol_id=idol_rows["Rin Amane"].id),
        ConcertPerformer(concert_id=concert_solo_showcase.id, idol_id=idol_rows["Kaede Shirogane"].id),
        ConcertPerformer(concert_id=concert_solo_showcase.id, idol_id=idol_rows["Yoru Kuon"].id),
        ConcertPerformer(concert_id=concert_countdown.id, group_id=sakura_prism.id),
        ConcertPerformer(concert_id=concert_kessho_finale.id, group_id=kessho_stars.id),
        ConcertPerformer(concert_id=concert_program_closing.id, group_id=program_heart.id),
    ])
    db.flush()

    # --- ticket types ------------------------------------------------------
    def tt(concert, tier, price, qty, sale_method="lottery"):
        row = TicketType(concert_id=concert.id, tier=tier, price=price, total_quantity=qty, sale_method=sale_method)
        db.add(row)
        return row

    tt_sakura_vip = tt(concert_sakura, "vip", 15000, 400)
    tt_sakura_premium_lottery = tt(concert_sakura, "premium", 7500, 6000)
    tt_sakura_regular_direct = tt(concert_sakura, "regular", 9000, 2000, sale_method="direct")

    tt(concert_nagisa, "vip", 11000, 250)
    tt(concert_nagisa, "regular", 5500, 4000)
    tt_nagisa_regular_direct = tt(concert_nagisa, "regular", 6800, 1500, sale_method="direct")

    tt_kessho_vip_direct = tt(concert_kessho, "vip", 21500, 200, sale_method="direct")
    tt_kessho_premium_lottery = tt(concert_kessho, "premium", 10000, 700)
    tt_kessho_regular_lottery = tt(concert_kessho, "regular", 6000, 800)

    tt(concert_yozora, "vip", 16000, 500)
    tt(concert_yozora, "premium", 8000, 25000)
    tt_yozora_regular_direct = tt(concert_yozora, "regular", 9800, 3500, sale_method="direct")

    tt(concert_program, "vip", 17000, 450)
    tt(concert_program, "premium", 8300, 8000)
    tt_program_regular_direct = tt(concert_program, "regular", 10500, 2500, sale_method="direct")

    tt(concert_solo_showcase, "vip", 24000, 800)
    tt(concert_solo_showcase, "premium", 11500, 40000)
    tt_showcase_regular_direct = tt(concert_solo_showcase, "regular", 13500, 4000, sale_method="direct")

    # Deliberately small capacities — 12 applicants against vip=3/premium=3/
    # regular=8 guarantees real competition at every tier, not just a
    # formality (see the lottery section below for exactly who wins/loses).
    tt_countdown_vip = tt(concert_countdown, "vip", 20000, 3)
    tt_countdown_premium = tt(concert_countdown, "premium", 14000, 3)
    tt_countdown_regular = tt(concert_countdown, "regular", 9000, 8)

    # Same deliberately-oversubscribed capacities as concert_countdown above
    # — reused for concert_kessho_finale/concert_program_closing below so
    # all three "ready to draw" concerts behave predictably the same way.
    tt_kessho_finale_vip = tt(concert_kessho_finale, "vip", 22000, 3)
    tt_kessho_finale_premium = tt(concert_kessho_finale, "premium", 12000, 3)
    tt_kessho_finale_regular = tt(concert_kessho_finale, "regular", 7500, 8)

    tt_program_closing_vip = tt(concert_program_closing, "vip", 18000, 3)
    tt_program_closing_premium = tt(concert_program_closing, "premium", 9500, 3)
    tt_program_closing_regular = tt(concert_program_closing, "regular", 6500, 8)
    db.flush()

    # --- direct sale campaigns: every direct-sale ticket type needs one now
    # (ticket_service.checkout_ticket) or it's simply unpurchasable — already
    # on sale, staying open through each concert's own event_datetime.
    for ticket_type, concert in [
        (tt_sakura_regular_direct, concert_sakura),
        (tt_nagisa_regular_direct, concert_nagisa),
        (tt_kessho_vip_direct, concert_kessho),
        (tt_yozora_regular_direct, concert_yozora),
        (tt_program_regular_direct, concert_program),
        (tt_showcase_regular_direct, concert_solo_showcase),
    ]:
        db.add(DirectSaleCampaign(
            ticket_type_id=ticket_type.id,
            sale_start_at=now - timedelta(days=10),
            sale_end_at=concert.event_datetime,
            status="open",
        ))
    db.flush()

    # --- categories (get-or-create — shared lookup table, not migration-seeded) ---
    cat_album = get_or_create_category(db, "Album", True)
    cat_single = get_or_create_category(db, "Single", True)
    cat_ep = get_or_create_category(db, "EP", True)
    cat_merch = get_or_create_category(db, "Merch", True)
    db.flush()

    CATEGORY_BY_KIND = {"album": cat_album, "single": cat_single, "ep": cat_ep}

    # --- marketplace: albums/singles/EPs ------------------------------------
    # (slug, title, price, description, quantity, kind, owner group/idol,
    #  release_date, track_count, format, genre names)
    releases = [
        ("sakura-prism-hanabi-ranman", "Sakura Prism - Hanabi Ranman (1st Full Album)", 3300,
         "Sakura Prism's debut full album — ten tracks of glossy, formation-ready idol pop.",
         5000, "album", sakura_prism, None, date(2026, 2, 20), 10, "physical", ["J-Pop", "Idol Pop"]),
        ("sakura-prism-sparkle-signal", "Sakura Prism - Sparkle Signal (Single)", 1200,
         "Sakura Prism's follow-up single, built around a fan-chant-ready chorus.",
         6000, "single", sakura_prism, None, date(2026, 6, 5), 2, "digital", ["J-Pop", "Pop"]),
        ("nagisa-melody-midnight-drive", "Nagisa Melody - Midnight Drive (Single)", 1500,
         "Nagisa Melody's title single from their Midnight Drive era — recorded live off the floor.",
         4000, "single", nagisa_melody, None, date(2026, 5, 12), 2, "physical", ["City Pop", "Acoustic"]),
        ("kessho-stars-starlight-oath", "Kessho Stars - Starlight Oath (Single)", 1300,
         "Kessho Stars' anime tie-in single, the opening theme for their in-universe franchise's latest season.",
         8000, "single", kessho_stars, None, date(2026, 7, 10), 2, "digital", ["Anime", "J-Pop"]),
        ("yozora-requiem-requiem-for-dawn", "Yozora Requiem - Requiem for Dawn (EP)", 2500,
         "Yozora Requiem's five-track gothic EP, written almost entirely in minor keys.",
         3000, "ep", yozora_requiem, None, date(2026, 8, 1), 5, "physical", ["Gothic", "Ballad"]),
        ("program-heart-recompile", "Program:HEART - Recompile (Digital Single)", 800,
         "Program:HEART's vocal-synth-forward debut single, self-produced and self-mixed.",
         9000, "single", program_heart, None, date(2026, 3, 18), 2, "digital", ["Vocaloid", "Electronic"]),
        ("program-heart-debug-heart", "Program:HEART - Debug Heart (EP)", 2000,
         "Program:HEART's second release, blending vocal-synth production with city-pop-leaning hooks.",
         4000, "ep", program_heart, None, date(2026, 9, 22), 4, "digital", ["Vocaloid", "City Pop"]),
        ("rin-amane-tideline", "Rin Amane - Tideline (Solo EP)", 2500,
         "Rin Amane's five-track solo EP, written by hand before a single note was recorded.",
         3000, "ep", None, idol_rows["Rin Amane"], date(2026, 4, 1), 5, "physical", ["R&B", "Ballad"]),
        ("kaede-shirogane-crimson-overture", "Kaede Shirogane - Crimson Overture (Single)", 1400,
         "Kaede Shirogane's rock-tinged anime insert-song single.",
         5000, "single", None, idol_rows["Kaede Shirogane"], date(2026, 6, 28), 2, "digital", ["Anime", "Rock"]),
        ("yoru-kuon-ghost-in-the-chorus", "Yoru Kuon - Ghost in the Chorus (Digital Album)", 3000,
         "Yoru Kuon's first solo album since stepping out from behind the DAW.",
         2500, "album", None, idol_rows["Yoru Kuon"], date(2026, 10, 5), 8, "digital", ["Vocaloid", "Electronic"]),
    ]

    for slug, title, price, description, qty, kind, group, idol, release_date, track_count, fmt, genres in releases:
        image_url = upload_fixture(f"{slug}.png", "products")
        product = Product(
            name=title, price=price, description=description,
            quantity=qty, category_id=CATEGORY_BY_KIND[kind].id, image_url=image_url,
        )
        db.add(product)
        db.flush()
        db.add(AlbumDetail(
            product_id=product.id,
            group_id=group.id if group else None,
            idol_id=idol.id if idol else None,
            release_date=release_date, track_count=track_count, format=fmt,
            cover_image_url=image_url,
        ))
        db.add_all([AlbumGenre(product_id=product.id, genre_id=genre_id(db, g)) for g in genres])
    db.flush()

    # --- marketplace: lightsticks --------------------------------------------
    # (slug, title, price, quantity, owner group/idol, edition, color name)
    lightsticks = [
        ("sakura-prism-lightstick", "Sakura Prism Official Lightstick", 5000, 2000,
         sakura_prism, None, "Ver. 1", "Cotton Candy Pink"),
        ("nagisa-melody-lightstick", "Nagisa Melody Official Lightstick", 4800, 1500,
         nagisa_melody, None, "Ver. 1", "Sky Mint"),
        ("kessho-stars-lightstick", "Kessho Stars Official Lightstick", 5200, 2500,
         kessho_stars, None, "Ver. 1", "Periwinkle Pop"),
        ("yozora-requiem-lightstick", "Yozora Requiem Official Lightstick", 4900, 1200,
         yozora_requiem, None, "Ver. 1", "Blood Rose"),
        ("program-heart-lightstick", "Program:HEART Official Lightstick", 5500, 1800,
         program_heart, None, "Ver. 1", "Synth Teal"),
        ("rin-amane-penlight", "Rin Amane Solo Penlight", 3300, 800,
         None, idol_rows["Rin Amane"], "Solo Ver.", "Ivory Frost"),
        ("kaede-shirogane-penlight", "Kaede Shirogane Solo Penlight", 3300, 800,
         None, idol_rows["Kaede Shirogane"], "Solo Ver.", "Crimson Ember"),
        ("yoru-kuon-penlight", "Yoru Kuon Solo Penlight", 3500, 600,
         None, idol_rows["Yoru Kuon"], "Solo Ver.", "Twilight Rose"),
    ]

    for slug, title, price, qty, group, idol, edition, color_name in lightsticks:
        image_url = upload_fixture(f"{slug}.png", "products")
        product = Product(
            name=title, price=price,
            description=f"Official {edition.lower()} lightstick.",
            quantity=qty, category_id=cat_merch.id, image_url=image_url,
        )
        db.add(product)
        db.flush()
        db.add(MerchDetail(
            product_id=product.id,
            group_id=group.id if group else None,
            idol_id=idol.id if idol else None,
            edition=edition, color_id=color_id(db, color_name),
        ))
    db.flush()

    # --- marketplace: group-branded merch (owned, same as the lightsticks
    # above — see project_status.md item 14/§5's "every product must be
    # owned" note. These two used to be created with no merch_details row at
    # all ("plain merch"), which was the exact shape of the cross-company
    # scoping bug: a manager from a different company could edit
    # "Sakura Prism Tour Hoodie" because nothing linked it back to Nova's
    # Sakura Prism group despite the name saying so.) --------------------
    branded_merch = [
        ("Sakura Prism Tour Hoodie", 6800, "Official Hanabi Ranman Tour hoodie.", 800, sakura_prism),
        ("Yozora Requiem Coffin Tote Bag", 2500, "Coffin-shaped tote bag from the Requiem for Dawn merch line.", 600, yozora_requiem),
    ]
    for name, price, description, qty, group in branded_merch:
        product = Product(name=name, price=price, description=description, quantity=qty, category_id=cat_merch.id)
        db.add(product)
        db.flush()
        db.add(MerchDetail(product_id=product.id, group_id=group.id))
    db.flush()

    # --- lottery: preferences, campaigns, entries ---------------------------
    # concert_sakura / concert_kessho: light data, entry windows still open —
    # for testing the apply/preference flow, not the draw itself.
    # tt_sakura_premium_lottery and tt_kessho_premium_lottery previously had
    # no campaign at all despite being sale_method="lottery" — filled in
    # here too. concert_kessho has no lottery vip tier at all (vip is
    # direct-sale only there — see the ticket types section).
    db.add_all([
        LotteryPreference(concert_id=concert_sakura.id, user_id=fan_alex.id, ticket_type_id=tt_sakura_vip.id, rank=1),
        LotteryPreference(concert_id=concert_sakura.id, user_id=fan_priya.id, ticket_type_id=tt_sakura_premium_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_kessho.id, user_id=fan_priya.id, ticket_type_id=tt_kessho_premium_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_kessho.id, user_id=fan_yuki.id, ticket_type_id=tt_kessho_regular_lottery.id, rank=1),
    ])
    db.flush()

    campaign_sakura_vip = LotteryCampaign(
        ticket_type_id=tt_sakura_vip.id,
        entry_start_at=now - timedelta(days=2), entry_end_at=now + timedelta(days=5),
        status="open",  # draw_at stays NULL — not drawn yet
    )
    campaign_sakura_regular = LotteryCampaign(
        ticket_type_id=tt_sakura_premium_lottery.id,
        entry_start_at=now - timedelta(days=2), entry_end_at=now + timedelta(days=5),
        status="open",  # draw_at stays NULL — not drawn yet
    )
    campaign_kessho_premium = LotteryCampaign(
        ticket_type_id=tt_kessho_premium_lottery.id,
        entry_start_at=now - timedelta(days=2), entry_end_at=now + timedelta(days=5),
        status="open",  # draw_at stays NULL — not drawn yet
    )
    campaign_kessho_regular = LotteryCampaign(
        ticket_type_id=tt_kessho_regular_lottery.id,
        entry_start_at=now - timedelta(days=2), entry_end_at=now + timedelta(days=5),
        status="open",  # draw_at stays NULL — not drawn yet
    )
    db.add_all([campaign_sakura_vip, campaign_sakura_regular, campaign_kessho_premium, campaign_kessho_regular])
    db.flush()

    db.add_all([
        LotteryEntry(campaign_id=campaign_sakura_vip.id, user_id=fan_alex.id),
        LotteryEntry(campaign_id=campaign_sakura_regular.id, user_id=fan_priya.id),
        LotteryEntry(campaign_id=campaign_kessho_regular.id, user_id=fan_yuki.id),
        # Was campaign_kessho_regular, but fan_priya's preference two blocks
        # up (line ~705) ranks tt_kessho_premium_lottery, not
        # tt_kessho_regular_lottery — trg_lottery_entries_require_preference
        # correctly rejected the mismatch. Points at the matching campaign now.
        LotteryEntry(campaign_id=campaign_kessho_premium.id, user_id=fan_priya.id),
    ])
    db.flush()

    # Three "ready to draw" concerts, one per company — entry_end_at already
    # in the PAST on every campaign below, so each is immediately drawable
    # via PUT /concerts/lottery-draw/{id} with no setup beyond running this
    # script. Same 12-fan pool, same 3-group cascade shape reused across all
    # three (seed_ready_to_draw_lottery, factored out from what used to be
    # concert_countdown-only logic) so every company's manager gets a
    # concert they can actually draw, not just Nova's:
    #   - vip: pure single-tier competition (5 candidates, 3 slots).
    #   - premium: a rank-1 crowd that already fills it (4 candidates, 3
    #     slots) before any vip rank-2 fallback gets a turn — 2 of the vip
    #     losers try their fallback here and find zero slots left.
    #   - regular: a rank-1 crowd well under capacity (3 candidates, 8
    #     slots), then 1 premium rank-1 loser's rank-2 fallback succeeds —
    #     the "lost rank 1, won rank 2" case the cascade exists for.
    group_a = [fan_alex, fan_priya, fan_marco, fan_yuki, fan_sofia]  # ranks vip=1, premium=2
    group_b = [fan_liam, fan_haruto, fan_emma, fan_noah]  # ranks premium=1, regular=2
    group_c = [fan_aiko, fan_diego, fan_chloe]  # ranks regular=1 only

    seed_ready_to_draw_lottery(db, concert_countdown, tt_countdown_vip, tt_countdown_premium, tt_countdown_regular, group_a, group_b, group_c)
    seed_ready_to_draw_lottery(db, concert_kessho_finale, tt_kessho_finale_vip, tt_kessho_finale_premium, tt_kessho_finale_regular, group_a, group_b, group_c)
    seed_ready_to_draw_lottery(db, concert_program_closing, tt_program_closing_vip, tt_program_closing_premium, tt_program_closing_regular, group_a, group_b, group_c)

    # --- one manually-issued ticket (admin stopgap path, see database-design.md §8) ---
    db.add(Ticket(
        ticket_type_id=tt_showcase_regular_direct.id, user_id=fan_marco.id,
        status="paid", issued_code="TIX-DEMO-0001",
    ))

    db.commit()

    print("Seed data created:")
    print(f"  - 3 management companies, 16 users (password for all: {SEED_PASSWORD})")
    print("    admin@example.com (admin)")
    print("    manager.nova@example.com / manager.starlight@example.com / manager.kuroyuri@example.com (manager)")
    print("    alex/priya/marco/yuki/sofia/liam/haruto/emma/noah/aiko/diego/chloe.fan@example.com (12 fans)")
    print("  - 5 groups (Sakura Prism, Nagisa Melody, Kessho Stars, Yozora Requiem, Program:HEART),")
    print("    22 group idols + 3 solo idols = 25 idols total, each with a generated profile image")
    print("  - 6 venues, 9 concerts, 27 ticket types across lottery + direct sale methods")
    print("    (concert_kessho's vip tier is direct-sale only, no lottery)")
    print("  - 6 direct sale campaigns — one per direct-sale ticket type, already on sale via")
    print("    POST /tickets/checkout (concert_countdown/concert_kessho_finale/concert_program_closing")
    print("    have no direct-sale tier at all)")
    print("  - 10 albums/singles/EPs with genres + cover art, 10 merch items (8 lightsticks + 2 group-branded), all owned")
    print("  - 13 lottery campaigns: 4 light ones (still-open entry windows, sakura vip+premium, kessho premium+regular) plus")
    print("    9 across 3 'ready to draw' concerts — one per company (Sakura Prism/Kessho Stars/Program:HEART),")
    print("    vip/premium/regular each, entry window already closed — draw any of them via")
    print("    PUT /concerts/lottery-draw/{id} as that company's own manager, with the same 12 fans'")
    print("    preferences + entries feeding the cascade in all three")
    print("  - 1 manually-issued ticket")


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


def main():
    db = SessionLocal()
    try:
        already_seeded = db.query(ManagementCompany).filter(ManagementCompany.name == "Nova Entertainment").first()
        if already_seeded:
            print("Seed data already present (found 'Nova Entertainment') — skipping.")
            return
        seed(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
