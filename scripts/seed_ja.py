"""Japanese-language seed script — the same fictional roster, venues, concerts,
ticket types, marketplace lineup, and lottery data as scripts/seed.py, with
every display string (company/group/idol/user names, descriptions, concert
titles, venue names and addresses, product titles) written in Japanese.

Structure, quantities, prices, dates, and lottery shapes are identical to
seed.py; only the text differs. Lookup keys stay in English because they
match migration-seeded rows or fixture filenames: idol color / position /
genre names, category names, and the romaji keys used to find each idol's
portrait in tests/fixtures/idols/.

Alternative to seed.py, not additive: both create the same user emails, so
only one of them can run against a given database. The sentinel check below
skips if either version's data is already present.

Run from the repo root inside the app container (after `alembic upgrade head`):
    docker compose exec app python scripts/seed_ja.py

Uses the same SEED_PASSWORD handling as seed.py.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed import (  # noqa: E402
    SEED_PASSWORD,
    _slug,
    color_id,
    genre_id,
    get_or_create_category,
    position_id,
    seed_ready_to_draw_lottery,
    upload_fixture,
)

from app.cache.cache_service import CacheService  # noqa: E402
from app.db.base import (  # noqa: E402
    AlbumDetail,
    AlbumGenre,
    Concert,
    ConcertPerformer,
    DirectSaleCampaign,
    Group,
    Idol,
    IdolPosition,
    LotteryCampaign,
    LotteryEntry,
    LotteryPreference,
    ManagementCompany,
    MerchDetail,
    Product,
    Ticket,
    TicketType,
    Users,
    Venue,
)
from app.db.session import session as SessionLocal  # noqa: E402
from app.utils.hashing import hash_password  # noqa: E402

SENTINEL_COMPANY_JA = "ノヴァ・エンターテインメント"
SENTINEL_COMPANY_EN = "Nova Entertainment"


def seed(db):
    now = datetime.now(timezone.utc)
    LOTTERY_ENTRY_CLOSE_DEC = datetime(2026, 12, 15, tzinfo=timezone.utc)

    # --- 事務所 (management companies) ------------------------------------
    nova = ManagementCompany(
        name=SENTINEL_COMPANY_JA,
        description="東京を拠点に、キラキラしたラジオ映えのJ-POPと、肩の力が抜けたシティポップ・リバイバルを手がけるレーベル。",
        contact_email="contact@nova-entertainment.example",
    )
    starlight = ManagementCompany(
        name="スターライト・メディア",
        description="アニメと二人三脚で歩むアイドル大手。ヒットチャートと凝ったステージコンセプト、タイアップ楽曲を両立させる。",
        contact_email="contact@starlight-media.example",
    )
    kuroyuri = ManagementCompany(
        name="黒百合レコード",
        description="ゴシックな美学とボカロ寄りのサウンドプロデュースに振り切ったオルタナ系アイドルレーベル。",
        contact_email="contact@kuroyuri-records.example",
    )
    db.add_all([nova, starlight, kuroyuri])
    db.flush()

    # --- ユーザー (users) ---------------------------------------------------
    def user(name, email, role, company=None):
        return Users(
            name=name, email=email,
            hashed_password=hash_password(SEED_PASSWORD), role=role,
            company_id=company.id if company else None,
            is_active=True, is_verified=True,
        )

    admin = user("管理者", "admin@example.com", "admin")
    manager_nova = user("瀬川 直美", "manager.nova@example.com", "manager", nova)
    manager_starlight = user("荒川 健二", "manager.starlight@example.com", "manager", starlight)
    manager_kuroyuri = user("各務 ゆりあ", "manager.kuroyuri@example.com", "manager", kuroyuri)
    fan_alex = user("アレックス・チェン", "alex.fan@example.com", "fan")
    fan_priya = user("プリヤ・ナイル", "priya.fan@example.com", "fan")
    fan_marco = user("マルコ・シルバ", "marco.fan@example.com", "fan")
    fan_yuki = user("田中 ゆき", "yuki.fan@example.com", "fan")
    fan_sofia = user("ソフィア・ロッシ", "sofia.fan@example.com", "fan")
    fan_liam = user("リアム・オコナー", "liam.fan@example.com", "fan")
    fan_haruto = user("水島 陽翔", "haruto.fan@example.com", "fan")
    fan_emma = user("エマ・ラーソン", "emma.fan@example.com", "fan")
    fan_noah = user("ノア・キム", "noah.fan@example.com", "fan")
    fan_aiko = user("藤原 愛子", "aiko.fan@example.com", "fan")
    fan_diego = user("ディエゴ・フェルナンデス", "diego.fan@example.com", "fan")
    fan_chloe = user("クロエ・デュボワ", "chloe.fan@example.com", "fan")
    db.add_all([
        admin, manager_nova, manager_starlight, manager_kuroyuri,
        fan_alex, fan_priya, fan_marco, fan_yuki,
        fan_sofia, fan_liam, fan_haruto, fan_emma, fan_noah, fan_aiko, fan_diego, fan_chloe,
    ])
    db.flush()

    # --- グループ (groups) --------------------------------------------------
    sakura_prism = Group(
        company_id=nova.id, name="桜プリズム",
        debut_date=date(2022, 4, 8),
        description="キャッチーなフック、寸分違わぬフォーメーション、そして常に全力の笑顔が武器の5人組アイドルポップユニット。",
    )
    nagisa_melody = Group(
        company_id=nova.id, name="渚メロディ",
        debut_date=date(2021, 6, 21),
        description="生楽器と色褪せた夏のハーモニーで魅せる、あえてゆったりしたシティポップ・リバイバル系の4人組バンドアイドル。",
    )
    kessho_stars = Group(
        company_id=starlight.id, name="結晶スターズ",
        debut_date=date(2023, 1, 14),
        description="作中の魔法少女フランチャイズのOP・EDテーマをそのまま持ち曲にする、5人組アニメタイアップ・アイドルユニット。",
    )
    yozora_requiem = Group(
        company_id=kuroyuri.id, name="夜空レクイエム",
        debut_date=date(2020, 10, 31),
        description="短調のバラード、ほぼ暗闇のステージ、そして決して笑わない宣材写真。4人組ゴシックアイドルユニット。",
    )
    program_heart = Group(
        company_id=kuroyuri.id, name="プログラム:ハート",
        debut_date=date(2022, 11, 3),
        description="ボカロ寄りサウンドの4人組デジタルアイドルユニット。全曲のミックスは今もリーダーが自ら手がけている。",
    )
    db.add_all([sakura_prism, nagisa_melody, kessho_stars, yozora_requiem, program_heart])
    db.flush()

    # --- アイドル (idols) ----------------------------------------------------
    # (romaji key for fixture/lookup, name, company, group, color, dob,
    #  hometown, short_intro, personality, positions[primary first])
    idols = [
        ("Hinata Kisaragi", "如月 ひなた", nova, sakura_prism, "Cotton Candy Pink", date(1999, 4, 12), "神奈川県横浜市",
         "桜プリズムのリーダー兼メインボーカル。",
         "どこまでも前向きなグループのお母さん。通し練習の前には必ずスタジオの鏡に謝り、ファンの名前は一度会えば絶対に忘れない。",
         ["Leader", "Main Vocalist"]),
        ("Momoka Serizawa", "芹沢 桃香", nova, sakura_prism, "Peach Sorbet", date(2000, 8, 22), "東京都",
         "桜プリズムのセンター兼リードダンサー。",
         "負けず嫌いの完璧主義者。自分の振り付けをコマ送りで見返し、一度も「これで十分」と言ったことがない。",
         ["Center", "Lead Dancer"]),
        ("Yui Amamiya", "雨宮 ゆい", nova, sakura_prism, "Butter Yellow", date(2001, 11, 3), "京都府京都市",
         "桜プリズムのボーカル担当。",
         "ステージの外ではいつも眠そうなのに、マイクが入った瞬間グループ随一の歌唱力を発揮する。その秘密は誰にもわからない。",
         ["Vocalist"]),
        ("Riko Fujimori", "藤森 莉子", nova, sakura_prism, "Tangerine Pop", date(2003, 2, 17), "大阪府大阪市",
         "桜プリズムのラップ担当。",
         "話す言葉はすべて音ゲーのたとえ。ファンミーティングはボス戦扱いで、毎回Sランクを狙っている。",
         ["Rapper"]),
        ("Nozomi Aizawa", "相沢 のぞみ", nova, sakura_prism, "Sakura Blossom", date(2005, 5, 30), "北海道札幌市",
         "桜プリズムの最年少メンバー兼ビジュアル担当。",
         "最年少なのに中身は大人。ヴィンテージのカセットテープを集め、スタッフの敬語の間違いをそっと直してくれる。",
         ["Maknae", "Visual"]),

        ("Sora Minase", "水瀬 そら", nova, nagisa_melody, "Sky Mint", date(1998, 6, 9), "福岡県福岡市",
         "渚メロディのリーダー兼ギタリスト。",
         "サーフロック信者。どの曲にも夕暮れのビーチみたいなブリッジが必要だと信じていて、曲作りの場ではたいてい押し切ってしまう。",
         ["Leader", "Guitarist"]),
        ("Ao Tachibana", "橘 あお", nova, nagisa_melody, "Baby Blue", date(1999, 12, 25), "兵庫県神戸市",
         "渚メロディのベーシスト兼ボーカル。",
         "無表情のまま淡々と一言ボケを繰り出す、MCのすべてがシュールなツッコミ待ちのコメディアン。",
         ["Bassist", "Vocalist"]),
        ("Nagi Hoshikawa", "星川 凪", nova, nagisa_melody, "Mint Cream", date(2000, 3, 14), "愛知県名古屋市",
         "渚メロディのキーボード担当。",
         "深夜3時にグループの曲をlo-fiリミックスし、バレバレの別名義でこっそりアップしている。",
         ["Keyboardist"]),
        ("Kanade Umino", "海野 奏", nova, nagisa_melody, "Lilac Bloom", date(2002, 9, 8), "沖縄県那覇市",
         "渚メロディのドラマー兼最年少メンバー。",
         "元競泳選手。ドラムのフィルはリレーの引き継ぎのように正確で、息もつかせず、決して遅れない。",
         ["Drummer", "Maknae"]),

        ("Akira Hoshimiya", "星宮 あきら", starlight, kessho_stars, "Periwinkle Pop", date(1999, 1, 5), "千葉県千葉市",
         "結晶スターズのリーダー兼メインボーカル。",
         "少年漫画の主人公のような宣言口調で話し、毎回のライブを本気で「最終決戦」だと思っている。なぜかそれがうまくいく。",
         ["Leader", "Main Vocalist"]),
        ("Ren Kazahaya", "風早 れん", starlight, kessho_stars, "Golden Hour", date(2000, 7, 19), "東京都",
         "結晶スターズのリードダンサー兼ビジュアル担当。",
         "魔法少女アニメの役のオーディションに落ちたものの、そのキャラの主題歌を歌うことに。以来「ネタとして」マント姿でステージに立ち続けている。",
         ["Lead Dancer", "Visual"]),
        ("Towa Kirishima", "霧島 とわ", starlight, kessho_stars, "Amber Glow", date(2001, 10, 2), "宮城県仙台市",
         "結晶スターズのラップ担当。",
         "ラップ詞の余白にバトルシーンの振り付けメモを書き込み、どのブリッジにも「パワーアップの瞬間」が必要だと譲らない。",
         ["Rapper"]),
        ("Hikaru Otonashi", "音無 ひかる", starlight, kessho_stars, "Neon Cyan", date(2002, 4, 27), "神奈川県横浜市",
         "結晶スターズのボーカル担当。",
         "声優の代役のような熱量の持ち主。タイアップアニメのセリフを全部暗記していて、頼まれなくてもキャラになりきって再現する。",
         ["Vocalist"]),
        ("Yuzuki Amagi", "天城 柚月", starlight, kessho_stars, "Bubblegum Purple", date(2004, 12, 11), "広島県広島市",
         "結晶スターズの最年少メンバー兼ダンサー。",
         "どのステージもイベント会場のトークショーのように楽しみ、前回のライブのコスプレを覚えていて特定のファンに手を振る。",
         ["Maknae", "Dancer"]),

        ("Aoi Kurenai", "紅 あおい", kuroyuri, yozora_requiem, "Onyx Black", date(1998, 10, 31), "東京都",
         "夜空レクイエムのリーダー兼メインボーカル。",
         "物腰は柔らかいのに歌詞は容赦なく暗い。「雰囲気のため」にほぼ真っ暗な中でリハーサルをすると言って聞かない。",
         ["Leader", "Main Vocalist"]),
        ("Suzune Yamikawa", "闇川 鈴音", kuroyuri, yozora_requiem, "Blood Rose", date(1999, 6, 13), "神奈川県横浜市",
         "夜空レクイエムのボーカル担当。",
         "クラシックのオペラ出身からオルタナアイドルへ転身。アレンジが求めていようといまいと、歌の途中でアリアを歌い上げる。",
         ["Vocalist"]),
        ("Karen Shirayuki", "白雪 花恋", kuroyuri, yozora_requiem, "Plum Wine", date(2001, 2, 8), "北海道札幌市",
         "夜空レクイエムのダンサー兼ビジュアル担当。",
         "踊るというよりステージに取り憑いているかのような振り付け。宣材写真では意地でも笑わない。",
         ["Dancer", "Visual"]),
        ("Mizuki Tsukishiro", "月城 美月", kuroyuri, yozora_requiem, "Deep Indigo", date(2003, 9, 21), "長崎県長崎市",
         "夜空レクイエムの最年少メンバー兼ボーカル。",
         "リハーサルの合間にホラー短編を書き、グループのステージコンセプトを怪談話のように練り上げていく。",
         ["Maknae", "Vocalist"]),

        ("Mira Kanade", "奏 ミラ", kuroyuri, program_heart, "Synth Teal", date(2000, 5, 5), "東京都",
         "プログラム:ハートのリーダー兼プロデューサー。",
         "宅録ボカロPとしてスタートし、今も朝4時にグループの曲をミックスしている。DAWには誰にも触らせない。",
         ["Leader", "Producer"]),
        ("Rio Kirisame", "霧雨 リオ", kuroyuri, program_heart, "Moonlight Silver", date(2001, 8, 16), "神奈川県横浜市",
         "プログラム:ハートのボーカル担当。",
         "ステージ上ではわざと合成音声のような平坦な口調、普段はいたって普通。キャラなのかどうか、誰も意見が一致しない。",
         ["Vocalist"]),
        ("Nana Shirakawa", "白川 なな", kuroyuri, program_heart, "Ghost Lavender", date(2002, 1, 29), "大阪府大阪市",
         "プログラム:ハートのダンサー。",
         "振り付けは0.5倍速で一度見れば二度と見返す必要がない、グループ随一の驚異的な覚えの早さ。",
         ["Dancer"]),
        ("Kohaku Amemiya", "雨宮 琥珀", kuroyuri, program_heart, "Pastel Aqua", date(2004, 11, 7), "京都府京都市",
         "プログラム:ハートの最年少メンバー兼ボーカル。",
         "ソロパートの前には必ずグリッチ音を入れることにこだわり、プロデューサーにカットさせたことは一度もない。",
         ["Maknae", "Vocalist"]),

        ("Rin Amane", "天音 りん", nova, None, "Ivory Frost", date(1997, 3, 2), "神奈川県横須賀市",
         "シネマティックなR&Bで知られるソロアーティスト。",
         "歌詞はすべて紙のノートに手書きしてから打ち込む。デモ録りで一度も泣かなかった曲はリリースしない。",
         ["Vocalist"]),
        ("Kaede Shirogane", "白銀 楓", starlight, None, "Crimson Ember", date(1998, 9, 14), "東京都",
         "アニメ挿入歌のスペシャリスト。",
         "アニメのヒロイン役のオーディションに落ち、代わりにそのキャラの主題歌を任された。以来、ステージではマント姿しか見せない。",
         ["Vocalist"]),
        ("Yoru Kuon", "久遠 ヨル", kuroyuri, None, "Twilight Rose", date(1996, 12, 20), "北海道札幌市",
         "ボカロPからソロシンガーへ転身。",
         "元は顔出しなしのボカロP。しぶしぶスポットライトの下に出てきた今も、毎公演の1番だけは半透明のスクリーン越しに歌う。",
         ["Producer", "Vocalist"]),
    ]

    idol_rows = {}
    for key, name, company, group, color_name, dob, hometown, intro, personality, positions in idols:
        image_url = upload_fixture(f"{_slug(key)}.png", "idols")
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
        idol_rows[key] = row
        for i, pos_name in enumerate(positions):
            db.add(IdolPosition(idol_id=row.id, position_id=position_id(db, pos_name), is_primary=(i == 0)))
    db.flush()

    # --- 会場 (venues) -------------------------------------------------------
    grove_hall = Venue(name="ザ・グローブホール", address="中央区大名2-14", city="福岡市",
                       country="日本", total_capacity=8000, contact_info="events@grovehall.example")
    skyline_arena = Venue(name="スカイラインアリーナ", address="中区那古野1-1", city="名古屋市",
                          country="日本", total_capacity=15000, contact_info="booking@skylinearena.example")
    harbor_point = Venue(name="ハーバーポイント野外劇場", address="西区みなとみらい1-1", city="横浜市",
                         country="日本", total_capacity=35000, contact_info="events@harborpoint.example")
    riverside_stadium = Venue(name="リバーサイドスタジアム", address="中央区新都心8", city="さいたま市",
                              country="日本", total_capacity=55000, contact_info="booking@riversidestadium.example")
    crescent_hall = Venue(name="クレセントホール", address="クレセント通り5-1", city="東京都",
                          country="日本", total_capacity=12000, contact_info="events@crescenthall.example")
    starlight_dome = Venue(name="スターライトドーム", address="難波大通3-2", city="大阪市",
                           country="日本", total_capacity=30000, contact_info="booking@starlightdome.example")
    db.add_all([grove_hall, skyline_arena, harbor_point, riverside_stadium, crescent_hall, starlight_dome])
    db.flush()

    # --- 公演・出演者 (concerts & performers) --------------------------------
    concert_sakura = Concert(
        company_id=nova.id, venue_id=crescent_hall.id,
        title="桜プリズム「花火爛漫」ツアー 東京公演",
        description="桜プリズム「花火爛漫」ツアーの地元・東京公演。",
        capacity=11000,
        event_datetime=LOTTERY_ENTRY_CLOSE_DEC + timedelta(days=14),
        doors_open_at=LOTTERY_ENTRY_CLOSE_DEC + timedelta(days=14, hours=-1), status="on_sale",
    )
    concert_nagisa = Concert(
        company_id=nova.id, venue_id=grove_hall.id,
        title="渚メロディ「ミッドナイト・ドライブ」ライブ",
        description="フルバンド編成で贈る、渚メロディのシティポップな一夜。",
        capacity=7000, event_datetime=now + timedelta(days=20),
        doors_open_at=now + timedelta(days=20, hours=-1), status="on_sale",
    )
    concert_kessho = Concert(
        company_id=starlight.id, venue_id=starlight_dome.id,
        title="結晶スターズ「星の誓い」ツアー 大阪公演",
        description="アニメタイアップ楽曲を軸に構成した、結晶スターズのアリーナ公演。",
        capacity=28000,
        event_datetime=LOTTERY_ENTRY_CLOSE_DEC + timedelta(days=21),
        doors_open_at=LOTTERY_ENTRY_CLOSE_DEC + timedelta(days=21, hours=-1), status="scheduled",
    )
    concert_yozora = Concert(
        company_id=kuroyuri.id, venue_id=harbor_point.id,
        title="夜空レクイエム「夜明けへのレクイエム」",
        description="ほぼ全編を闇の中で演出する、夜空レクイエムのゴシックな野外公演。",
        capacity=32000, event_datetime=now + timedelta(days=50),
        doors_open_at=now + timedelta(days=50, hours=-1), status="scheduled",
    )
    concert_program = Concert(
        company_id=kuroyuri.id, venue_id=skyline_arena.id,
        title="プログラム:ハート「リコンパイル」ライブ",
        description="ボカロサウンドで魅せる、プログラム:ハート初のアリーナ公演。",
        capacity=13500, event_datetime=now + timedelta(days=35),
        doors_open_at=now + timedelta(days=35, hours=-1), status="on_sale",
    )
    concert_solo_showcase = Concert(
        company_id=nova.id, venue_id=riverside_stadium.id,
        title="ノヴァ×黒百合 ソロ・ショーケース",
        description="天音りん、白銀楓、久遠ヨルのソロアーティスト3組が出演する、レーベル合同ショーケース。",
        capacity=50000, event_datetime=now + timedelta(days=15),
        doors_open_at=now + timedelta(days=15, hours=-1), status="on_sale",
    )
    concert_countdown = Concert(
        company_id=nova.id, venue_id=crescent_hall.id,
        title="桜プリズム ニューイヤー・カウントダウンライブ",
        description="大晦日のカウントダウン公演。桜プリズムにとって一年で最も倍率の高い抽選。",
        capacity=11000, event_datetime=now + timedelta(days=25),
        doors_open_at=now + timedelta(days=25, hours=-1), status="on_sale",
    )
    concert_kessho_finale = Concert(
        company_id=starlight.id, venue_id=starlight_dome.id,
        title="結晶スターズ「永遠の誓い」ファイナル",
        description="結晶スターズのシーズンファイナル。アニメタイアップ・フランチャイズのクライマックスを飾る公演。",
        capacity=28000, event_datetime=now + timedelta(days=40),
        doors_open_at=now + timedelta(days=40, hours=-1), status="on_sale",
    )
    concert_program_closing = Concert(
        company_id=kuroyuri.id, venue_id=skyline_arena.id,
        title="プログラム:ハート「システム・シャットダウン」ファイナル",
        description="プログラム:ハート「リコンパイル」期を締めくくるラスト公演。",
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

    # --- 券種 (ticket types) — same tiers/prices/quantities as seed.py -------
    def tt(concert, tier, price, qty, sale_method="lottery"):
        row = TicketType(concert_id=concert.id, tier=tier, price=price, total_quantity=qty, sale_method=sale_method)
        db.add(row)
        return row

    tt_sakura_vip = tt(concert_sakura, "vip", 15000, 400)
    tt_sakura_premium_lottery = tt(concert_sakura, "premium", 7500, 6000)
    tt_sakura_regular_direct = tt(concert_sakura, "regular", 9000, 2000, sale_method="direct")

    tt_nagisa_vip = tt(concert_nagisa, "vip", 11000, 250)
    tt_nagisa_regular_lottery = tt(concert_nagisa, "regular", 5500, 4000)
    tt_nagisa_regular_direct = tt(concert_nagisa, "regular", 6800, 1500, sale_method="direct")

    tt_kessho_vip_direct = tt(concert_kessho, "vip", 21500, 200, sale_method="direct")
    tt_kessho_premium_lottery = tt(concert_kessho, "premium", 10000, 700)
    tt_kessho_regular_lottery = tt(concert_kessho, "regular", 6000, 800)

    tt_yozora_vip = tt(concert_yozora, "vip", 16000, 500)
    tt_yozora_premium_lottery = tt(concert_yozora, "premium", 8000, 25000)
    tt_yozora_regular_direct = tt(concert_yozora, "regular", 9800, 3500, sale_method="direct")

    tt_program_vip = tt(concert_program, "vip", 17000, 450)
    tt_program_premium_lottery = tt(concert_program, "premium", 8300, 8000)
    tt_program_regular_direct = tt(concert_program, "regular", 10500, 2500, sale_method="direct")

    tt_showcase_vip = tt(concert_solo_showcase, "vip", 24000, 800)
    tt_showcase_premium_lottery = tt(concert_solo_showcase, "premium", 11500, 40000)
    tt_showcase_regular_direct = tt(concert_solo_showcase, "regular", 13500, 4000, sale_method="direct")

    tt_countdown_vip = tt(concert_countdown, "vip", 20000, 3)
    tt_countdown_premium = tt(concert_countdown, "premium", 14000, 3)
    tt_countdown_regular = tt(concert_countdown, "regular", 9000, 8)

    tt_kessho_finale_vip = tt(concert_kessho_finale, "vip", 22000, 3)
    tt_kessho_finale_premium = tt(concert_kessho_finale, "premium", 12000, 3)
    tt_kessho_finale_regular = tt(concert_kessho_finale, "regular", 7500, 8)

    tt_program_closing_vip = tt(concert_program_closing, "vip", 18000, 3)
    tt_program_closing_premium = tt(concert_program_closing, "premium", 9500, 3)
    tt_program_closing_regular = tt(concert_program_closing, "regular", 6500, 8)
    db.flush()

    # --- 一般販売 (direct sale campaigns) ------------------------------------
    DIRECT_SALE_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
    DIRECT_SALE_END = datetime(2026, 12, 31, tzinfo=timezone.utc)
    for ticket_type in [
        tt_sakura_regular_direct, tt_nagisa_regular_direct, tt_kessho_vip_direct,
        tt_yozora_regular_direct, tt_program_regular_direct, tt_showcase_regular_direct,
    ]:
        db.add(DirectSaleCampaign(
            ticket_type_id=ticket_type.id,
            sale_start_at=DIRECT_SALE_START,
            sale_end_at=DIRECT_SALE_END,
            status="open",
        ))
    db.flush()

    # --- categories: English names, shared with seed.py's lookup rows -------
    cat_album = get_or_create_category(db, "Album", True)
    cat_single = get_or_create_category(db, "Single", True)
    cat_ep = get_or_create_category(db, "EP", True)
    cat_merch = get_or_create_category(db, "Merch", True)
    db.flush()

    CATEGORY_BY_KIND = {"album": cat_album, "single": cat_single, "ep": cat_ep}

    # --- マーケット: アルバム/シングル/EP ------------------------------------
    # (fixture slug, title, price, description, quantity, kind, owner group/idol,
    #  release_date, track_count, format, genre names)
    releases = [
        ("sakura-prism-hanabi-ranman", "桜プリズム『花火爛漫』(1stフルアルバム)", 3300,
         "桜プリズムのデビューフルアルバム。フォーメーション映えするキラキラのアイドルポップ全10曲。",
         5000, "album", sakura_prism, None, date(2026, 2, 20), 10, "physical", ["J-Pop", "Idol Pop"]),
        ("sakura-prism-sparkle-signal", "桜プリズム『スパークル・シグナル』(シングル)", 1200,
         "コールが映えるサビを軸にした、桜プリズムの続くシングル。",
         6000, "single", sakura_prism, None, date(2026, 6, 5), 2, "digital", ["J-Pop", "Pop"]),
        ("nagisa-melody-midnight-drive", "渚メロディ『ミッドナイト・ドライブ』(シングル)", 1500,
         "一発録りで収録した、渚メロディ「ミッドナイト・ドライブ」期の表題シングル。",
         4000, "single", nagisa_melody, None, date(2026, 5, 12), 2, "physical", ["City Pop", "Acoustic"]),
        ("kessho-stars-starlight-oath", "結晶スターズ『星の誓い』(シングル)", 1300,
         "作中フランチャイズ最新シーズンのOPテーマとなった、結晶スターズのアニメタイアップシングル。",
         8000, "single", kessho_stars, None, date(2026, 7, 10), 2, "digital", ["Anime", "J-Pop"]),
        ("yozora-requiem-requiem-for-dawn", "夜空レクイエム『夜明けへのレクイエム』(EP)", 2500,
         "ほぼ全曲を短調で書き上げた、夜空レクイエムのゴシックEP全5曲。",
         3000, "ep", yozora_requiem, None, date(2026, 8, 1), 5, "physical", ["Gothic", "Ballad"]),
        ("program-heart-recompile", "プログラム:ハート『リコンパイル』(デジタルシングル)", 800,
         "セルフプロデュース・セルフミックスで仕上げた、ボカロサウンド全開のデビューシングル。",
         9000, "single", program_heart, None, date(2026, 3, 18), 2, "digital", ["Vocaloid", "Electronic"]),
        ("program-heart-debug-heart", "プログラム:ハート『デバッグ・ハート』(EP)", 2000,
         "ボカロサウンドにシティポップ寄りのフックを掛け合わせた、プログラム:ハートの2ndリリース。",
         4000, "ep", program_heart, None, date(2026, 9, 22), 4, "digital", ["Vocaloid", "City Pop"]),
        ("rin-amane-tideline", "天音りん『タイドライン』(ソロEP)", 2500,
         "一音も録る前にすべて手書きで書き上げた、天音りんのソロEP全5曲。",
         3000, "ep", None, idol_rows["Rin Amane"], date(2026, 4, 1), 5, "physical", ["R&B", "Ballad"]),
        ("kaede-shirogane-crimson-overture", "白銀楓『クリムゾン・オーバーチュア』(シングル)", 1400,
         "ロック色の強い、白銀楓のアニメ挿入歌シングル。",
         5000, "single", None, idol_rows["Kaede Shirogane"], date(2026, 6, 28), 2, "digital", ["Anime", "Rock"]),
        ("yoru-kuon-ghost-in-the-chorus", "久遠ヨル『ゴースト・イン・ザ・コーラス』(デジタルアルバム)", 3000,
         "DAWの陰から一歩踏み出した久遠ヨルの、初のソロアルバム。",
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
        ))
        db.add_all([AlbumGenre(product_id=product.id, genre_id=genre_id(db, g)) for g in genres])
    db.flush()

    # --- マーケット: ペンライト (lightsticks) --------------------------------
    # (fixture slug, title, price, quantity, owner group/idol, edition, color name)
    lightsticks = [
        ("sakura-prism-lightstick", "桜プリズム 公式ペンライト", 5000, 2000,
         sakura_prism, None, "Ver. 1", "Cotton Candy Pink"),
        ("nagisa-melody-lightstick", "渚メロディ 公式ペンライト", 4800, 1500,
         nagisa_melody, None, "Ver. 1", "Sky Mint"),
        ("kessho-stars-lightstick", "結晶スターズ 公式ペンライト", 5200, 2500,
         kessho_stars, None, "Ver. 1", "Periwinkle Pop"),
        ("yozora-requiem-lightstick", "夜空レクイエム 公式ペンライト", 4900, 1200,
         yozora_requiem, None, "Ver. 1", "Blood Rose"),
        ("program-heart-lightstick", "プログラム:ハート 公式ペンライト", 5500, 1800,
         program_heart, None, "Ver. 1", "Synth Teal"),
        ("rin-amane-penlight", "天音りん ソロペンライト", 3300, 800,
         None, idol_rows["Rin Amane"], "Solo Ver.", "Ivory Frost"),
        ("kaede-shirogane-penlight", "白銀楓 ソロペンライト", 3300, 800,
         None, idol_rows["Kaede Shirogane"], "Solo Ver.", "Crimson Ember"),
        ("yoru-kuon-penlight", "久遠ヨル ソロペンライト", 3500, 600,
         None, idol_rows["Yoru Kuon"], "Solo Ver.", "Twilight Rose"),
    ]

    for slug, title, price, qty, group, idol, edition, color_name in lightsticks:
        image_url = upload_fixture(f"{slug}.png", "products")
        product = Product(
            name=title, price=price,
            description=f"公式ペンライト({edition})。",
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

    # --- マーケット: グループ公式グッズ (owned branded merch) ----------------
    branded_merch = [
        ("桜プリズム ツアーパーカー", 6800, "「花火爛漫」ツアー公式パーカー。", 800, sakura_prism),
        ("夜空レクイエム 棺型トートバッグ", 2500, "「夜明けへのレクイエム」グッズラインの棺型トートバッグ。", 600, yozora_requiem),
    ]
    for name, price, description, qty, group in branded_merch:
        product = Product(name=name, price=price, description=description, quantity=qty, category_id=cat_merch.id)
        db.add(product)
        db.flush()
        db.add(MerchDetail(product_id=product.id, group_id=group.id))
    db.flush()

    # --- 抽選: 希望・キャンペーン・応募 (same shape as seed.py) -------------
    db.add_all([
        LotteryPreference(concert_id=concert_sakura.id, user_id=fan_alex.id, ticket_type_id=tt_sakura_vip.id, rank=1),
        LotteryPreference(concert_id=concert_sakura.id, user_id=fan_priya.id, ticket_type_id=tt_sakura_premium_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_kessho.id, user_id=fan_priya.id, ticket_type_id=tt_kessho_premium_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_kessho.id, user_id=fan_yuki.id, ticket_type_id=tt_kessho_regular_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_nagisa.id, user_id=fan_marco.id, ticket_type_id=tt_nagisa_vip.id, rank=1),
        LotteryPreference(concert_id=concert_nagisa.id, user_id=fan_yuki.id, ticket_type_id=tt_nagisa_regular_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_yozora.id, user_id=fan_alex.id, ticket_type_id=tt_yozora_vip.id, rank=1),
        LotteryPreference(concert_id=concert_yozora.id, user_id=fan_priya.id, ticket_type_id=tt_yozora_premium_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_program.id, user_id=fan_marco.id, ticket_type_id=tt_program_vip.id, rank=1),
        LotteryPreference(concert_id=concert_program.id, user_id=fan_yuki.id, ticket_type_id=tt_program_premium_lottery.id, rank=1),
        LotteryPreference(concert_id=concert_solo_showcase.id, user_id=fan_alex.id, ticket_type_id=tt_showcase_vip.id, rank=1),
        LotteryPreference(concert_id=concert_solo_showcase.id, user_id=fan_priya.id, ticket_type_id=tt_showcase_premium_lottery.id, rank=1),
    ])
    db.flush()

    def open_campaign(ticket_type, entry_end_at):
        return LotteryCampaign(
            ticket_type_id=ticket_type.id,
            entry_start_at=now - timedelta(days=2), entry_end_at=entry_end_at,
            status="open",
        )

    campaign_sakura_vip = open_campaign(tt_sakura_vip, LOTTERY_ENTRY_CLOSE_DEC)
    campaign_sakura_regular = open_campaign(tt_sakura_premium_lottery, LOTTERY_ENTRY_CLOSE_DEC)
    campaign_kessho_premium = open_campaign(tt_kessho_premium_lottery, LOTTERY_ENTRY_CLOSE_DEC)
    campaign_kessho_regular = open_campaign(tt_kessho_regular_lottery, LOTTERY_ENTRY_CLOSE_DEC)
    campaign_nagisa_vip = open_campaign(tt_nagisa_vip, concert_nagisa.event_datetime - timedelta(days=7))
    campaign_nagisa_regular = open_campaign(tt_nagisa_regular_lottery, concert_nagisa.event_datetime - timedelta(days=7))
    campaign_yozora_vip = open_campaign(tt_yozora_vip, concert_yozora.event_datetime - timedelta(days=7))
    campaign_yozora_premium = open_campaign(tt_yozora_premium_lottery, concert_yozora.event_datetime - timedelta(days=7))
    campaign_program_vip = open_campaign(tt_program_vip, concert_program.event_datetime - timedelta(days=7))
    campaign_program_premium = open_campaign(tt_program_premium_lottery, concert_program.event_datetime - timedelta(days=7))
    campaign_showcase_vip = open_campaign(tt_showcase_vip, concert_solo_showcase.event_datetime - timedelta(days=7))
    campaign_showcase_premium = open_campaign(tt_showcase_premium_lottery, concert_solo_showcase.event_datetime - timedelta(days=7))
    db.add_all([
        campaign_sakura_vip, campaign_sakura_regular, campaign_kessho_premium, campaign_kessho_regular,
        campaign_nagisa_vip, campaign_nagisa_regular, campaign_yozora_vip, campaign_yozora_premium,
        campaign_program_vip, campaign_program_premium, campaign_showcase_vip, campaign_showcase_premium,
    ])
    db.flush()

    db.add_all([
        LotteryEntry(campaign_id=campaign_sakura_vip.id, user_id=fan_alex.id),
        LotteryEntry(campaign_id=campaign_sakura_regular.id, user_id=fan_priya.id),
        LotteryEntry(campaign_id=campaign_kessho_regular.id, user_id=fan_yuki.id),
        LotteryEntry(campaign_id=campaign_kessho_premium.id, user_id=fan_priya.id),
        LotteryEntry(campaign_id=campaign_nagisa_vip.id, user_id=fan_marco.id),
        LotteryEntry(campaign_id=campaign_nagisa_regular.id, user_id=fan_yuki.id),
        LotteryEntry(campaign_id=campaign_yozora_vip.id, user_id=fan_alex.id),
        LotteryEntry(campaign_id=campaign_yozora_premium.id, user_id=fan_priya.id),
        LotteryEntry(campaign_id=campaign_program_vip.id, user_id=fan_marco.id),
        LotteryEntry(campaign_id=campaign_program_premium.id, user_id=fan_yuki.id),
        LotteryEntry(campaign_id=campaign_showcase_vip.id, user_id=fan_alex.id),
        LotteryEntry(campaign_id=campaign_showcase_premium.id, user_id=fan_priya.id),
    ])
    db.flush()

    # Three "ready to draw" concerts, one per company — see seed.py for the cascade shape.
    group_a = [fan_alex, fan_priya, fan_marco, fan_yuki, fan_sofia]  # ranks vip=1, premium=2
    group_b = [fan_liam, fan_haruto, fan_emma, fan_noah]  # ranks premium=1, regular=2
    group_c = [fan_aiko, fan_diego, fan_chloe]  # ranks regular=1 only

    seed_ready_to_draw_lottery(db, concert_countdown, tt_countdown_vip, tt_countdown_premium, tt_countdown_regular, group_a, group_b, group_c)
    seed_ready_to_draw_lottery(db, concert_kessho_finale, tt_kessho_finale_vip, tt_kessho_finale_premium, tt_kessho_finale_regular, group_a, group_b, group_c)
    seed_ready_to_draw_lottery(db, concert_program_closing, tt_program_closing_vip, tt_program_closing_premium, tt_program_closing_regular, group_a, group_b, group_c)

    # --- 手動発券チケット1枚 (admin stopgap path) ---------------------------
    db.add(Ticket(
        ticket_type_id=tt_showcase_regular_direct.id, user_id=fan_marco.id,
        status="paid", issued_code="TIX-DEMO-0001",
    ))

    db.commit()

    # This script writes straight through SQLAlchemy, not the /add endpoints that
    # normally call these on a write — so a page cached (even as empty) before a
    # seed run would otherwise keep serving that stale result for up to
    # TTL_SECONDS after the data above is already in the database.
    CacheService.delete_cached_events_page()
    CacheService.delete_cached_manager_events_page()
    CacheService.delete_cached_members_page()
    CacheService.delete_cached_groups_page()
    CacheService.delete_cached_manager_groups_page()
    CacheService.delete_cached_manager_idols_page()
    CacheService.delete_cached_manager_idol_form_page()
    CacheService.delete_cached_venues()
    CacheService.delete_cached_management_companies()
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()

    print("シードデータ(日本語版)を作成しました:")
    print(f"  - 事務所3社、ユーザー16名(全員共通パスワード: {SEED_PASSWORD})")
    print("    admin@example.com (admin)")
    print("    manager.nova@example.com / manager.starlight@example.com / manager.kuroyuri@example.com (manager)")
    print("    alex/priya/marco/yuki/sofia/liam/haruto/emma/noah/aiko/diego/chloe.fan@example.com (ファン12名)")
    print("  - グループ5組(桜プリズム、渚メロディ、結晶スターズ、夜空レクイエム、プログラム:ハート)、")
    print("    グループメンバー22名 + ソロ3名 = アイドル計25名(プロフィール画像付き)")
    print("  - 会場6、公演9、券種27(抽選 + 一般販売)")
    print("  - 一般販売キャンペーン6件")
    print("  - アルバム/シングル/EP 10点、グッズ10点(ペンライト8 + グループ公式グッズ2)")
    print("  - 抽選キャンペーン21件: 受付中12件 + 即抽選可能な3公演 × vip/premium/regular の9件")
    print("  - 手動発券チケット1枚")


def main():
    db = SessionLocal()
    try:
        already_seeded = db.query(ManagementCompany).filter(
            ManagementCompany.name.in_([SENTINEL_COMPANY_JA, SENTINEL_COMPANY_EN])
        ).first()
        if already_seeded:
            print(f"シードデータは既に存在します('{already_seeded.name}' を検出)— スキップします。")
            return
        seed(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
