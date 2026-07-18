import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialized — call init_pool() at startup first")
    return _pool


async def ensure_runtime_schema() -> None:
    """Apply small idempotent Module 1/3 schema/seed updates at startup.

    Docker's init.sql only runs for a brand-new Postgres volume. These DDL/DML
    statements keep existing dev volumes compatible after backend upgrades.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Base tables. Docker's init.sql only runs on a brand-new Postgres volume;
        # a managed Postgres (e.g. Railway) runs no init.sql at all, so the base
        # tables must be created here as well or the ALTER/INSERT statements below
        # fail on a fresh database. All idempotent — statements are verbatim from
        # db/init.sql, kept in sync with it.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                native_language TEXT NOT NULL,
                nationality     TEXT NOT NULL,
                compressed_history JSONB,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geo_regions (
                id          SERIAL PRIMARY KEY,
                city        TEXT NOT NULL,
                zone_name   TEXT NOT NULL,
                center_lat  DOUBLE PRECISION NOT NULL,
                center_lon  DOUBLE PRECISION NOT NULL,
                radius_km   DOUBLE PRECISION NOT NULL DEFAULT 3.0,
                UNIQUE (city, zone_name)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_references (
                id           SERIAL PRIMARY KEY,
                item_name    TEXT NOT NULL,
                region       TEXT NOT NULL,
                category     TEXT NOT NULL DEFAULT 'general',
                price_vnd    DOUBLE PRECISION,
                mu_post      DOUBLE PRECISION,
                tau_post     DOUBLE PRECISION,
                sigma_data   DOUBLE PRECISION NOT NULL DEFAULT 0.3,
                n            INTEGER NOT NULL DEFAULT 0,
                sum_y        DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_price_references_region ON price_references (region)"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emergency_hotlines (
                id           SERIAL PRIMARY KEY,
                region       TEXT NOT NULL,
                service_type TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                notes        TEXT,
                source_url   TEXT,
                verified_at TIMESTAMPTZ,
                verification_status TEXT NOT NULL DEFAULT 'unverified'
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embassies (
                id           SERIAL PRIMARY KEY,
                nationality  TEXT NOT NULL,
                country_name TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                address      TEXT,
                region_hint  TEXT,
                source_url   TEXT,
                verified_at TIMESTAMPTZ,
                verification_status TEXT NOT NULL DEFAULT 'unverified'
            )
            """
        )
        await conn.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS compressed_history JSONB")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_turns (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id          UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                chunk_sequence_id   INTEGER,
                source_text         TEXT NOT NULL,
                clean_text          TEXT NOT NULL,
                reply               TEXT,
                translation         JSONB,
                threat              JSONB,
                scam_flags          JSONB,
                region              TEXT,
                response_payload    JSONB NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_turns_session_created ON chat_turns (session_id, created_at)")
        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_turns_session_chunk
            ON chat_turns (session_id, chunk_sequence_id)
            WHERE chunk_sequence_id IS NOT NULL
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threat_risk_state (
                session_id          UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                total_score         DOUBLE PRECISION NOT NULL DEFAULT 0,
                category_scores     JSONB NOT NULL DEFAULT '{}'::jsonb,
                escalation_history  JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sos_events (
                id                  SERIAL PRIMARY KEY,
                session_id          UUID NOT NULL REFERENCES sessions(id),
                lat                 DOUBLE PRECISION,
                lon                 DOUBLE PRECISION,
                region              TEXT,
                nationality         TEXT,
                threat_category     TEXT,
                threat_level        TEXT,
                source              TEXT,
                idempotency_key     TEXT,
                client_timestamp    TIMESTAMPTZ,
                location_text_vi    TEXT,
                location_text_en    TEXT,
                contacts_returned   JSONB,
                response_payload    JSONB,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS threat_level TEXT")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS source TEXT")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS idempotency_key TEXT")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS client_timestamp TIMESTAMPTZ")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS location_text_vi TEXT")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS location_text_en TEXT")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS contacts_returned JSONB")
        await conn.execute("ALTER TABLE sos_events ADD COLUMN IF NOT EXISTS response_payload JSONB")
        await conn.execute("ALTER TABLE emergency_hotlines ADD COLUMN IF NOT EXISTS source_url TEXT")
        await conn.execute("ALTER TABLE emergency_hotlines ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
        await conn.execute(
            "ALTER TABLE emergency_hotlines ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'unverified'"
        )
        await conn.execute("ALTER TABLE embassies ADD COLUMN IF NOT EXISTS source_url TEXT")
        await conn.execute("ALTER TABLE embassies ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
        await conn.execute(
            "ALTER TABLE embassies ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'unverified'"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sos_events_session_id ON sos_events (session_id)")
        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_sos_events_session_idempotency
            ON sos_events (session_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_emergency_hotlines_region_service_phone
            ON emergency_hotlines (region, service_type, phone_number)
            """
        )
        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_embassies_nationality_phone
            ON embassies (nationality, phone_number)
            """
        )
        await conn.execute(
            """
            INSERT INTO geo_regions (city, zone_name, center_lat, center_lon, radius_km) VALUES
                ('Hanoi', 'Old Quarter', 21.0333, 105.8500, 2.0),
                ('Sapa', 'Town Center', 22.3364, 103.8438, 3.0),
                ('Hoi An', 'Ancient Town', 15.8801, 108.3380, 2.0)
            ON CONFLICT DO NOTHING
            """
        )
        await conn.execute(
            """
            INSERT INTO emergency_hotlines (region, service_type, phone_number, notes) VALUES
                ('Vietnam', 'police', '113', 'Nationwide police emergency number in Vietnam'),
                ('Vietnam', 'medical', '115', 'Nationwide medical ambulance emergency number in Vietnam'),
                ('Vietnam', 'fire', '114', 'Nationwide fire and rescue emergency number in Vietnam'),
                ('Hanoi', 'police', '113', 'Cảnh sát phản ứng nhanh toàn quốc (Khu vực Hà Nội)'),
                ('Hanoi', 'medical', '115', 'Cấp cứu y tế khẩn cấp Hà Nội'),
                ('Hanoi', 'fire', '114', 'Phòng cháy chữa cháy cứu hộ cứu nạn Hà Nội'),
                ('Hanoi', 'tourist_police', '02438285858', 'Công an phường Hàng Trống (Hỗ trợ du khách Phố Cổ)'),
                ('Sapa', 'police', '113', 'Cảnh sát phản ứng nhanh (Khu vực Sa Pa / Lào Cai)'),
                ('Sapa', 'medical', '115', 'Cấp cứu Bệnh viện Đa khoa thị xã Sa Pa'),
                ('Sapa', 'tourist_police', '02143871226', 'Công an thị xã Sa Pa (Đường Thạch Sơn)'),
                ('Hoi An', 'police', '113', 'Cảnh sát phản ứng nhanh (Khu vực Hội An / Quảng Nam)'),
                ('Hoi An', 'medical', '115', 'Cấp cứu Bệnh viện Đa khoa Hội An'),
                ('Hoi An', 'tourist_police', '02353861304', 'Trung tâm Hỗ trợ Du khách thành phố Hội An')
            ON CONFLICT DO NOTHING
            """
        )
        await conn.execute(
            """
            INSERT INTO emergency_hotlines
                (region, service_type, phone_number, notes, source_url, verified_at, verification_status)
            VALUES
                ('Vietnam', 'general_emergency', '112',
                 'National 24/7 emergency line for incidents, disasters, and urgent assistance',
                 'https://eav.gov.vn/d/vi-VN/news-o/TONG-DAI-KHAN-CAP-QUOC-GIA-112-tiep-nhan-247-cac-thong-tin-SU-CO-THIEN-TAI-THAM-HOA-60-102-58621',
                 '2026-07-18T00:00:00+07'::timestamptz, 'verified')
            ON CONFLICT (region, service_type, phone_number) DO UPDATE SET
                notes = EXCLUDED.notes,
                source_url = EXCLUDED.source_url,
                verified_at = EXCLUDED.verified_at,
                verification_status = EXCLUDED.verification_status
            """
        )
        await conn.execute(
            """
            INSERT INTO embassies (nationality, country_name, phone_number, address, region_hint) VALUES
                ('KR', 'Hàn Quốc (South Korea)', '+84-24-3831-5111', 'Tầng 28 Lotte Center, 54 Liễu Giai, Ba Đình, Hà Nội', 'Hanoi'),
                ('CN', 'Trung Quốc (China)', '+84-24-3845-3736', '46 Hoàng Diệu, Ba Đình, Hà Nội', 'Hanoi'),
                ('US', 'Hoa Kỳ (United States)', '+84-24-3850-5000', 'Số 7 Láng Hạ, Ba Đình, Hà Nội', 'Hanoi'),
                ('GB', 'Vương quốc Anh (UK)', '+84-24-3936-0500', 'Tầng 4 Central Building, 31 Hai Bà Trưng, Hoàn Kiếm, Hà Nội', 'Hanoi'),
                ('AU', 'Úc (Australia)', '+84-24-3774-0100', 'Số 8 Đào Tấn, Ba Đình, Hà Nội', 'Hanoi'),
                ('JP', 'Nhật Bản (Japan)', '+84-24-3846-3000', 'Số 27 Liễu Giai, Ba Đình, Hà Nội', 'Hanoi'),
                ('SG', 'Singapore', '+84-24-3734-8001', 'Số 41-43 Trần Phú, Ba Đình, Hà Nội', 'Hanoi'),
                ('TW', 'Đài Loan (TECO)', '+84-24-3833-5501', 'Tầng 20 PVI Tower, 1 Phạm Văn Bạch, Cầu Giấy, Hà Nội', 'Hanoi')
            ON CONFLICT DO NOTHING
            """
        )
