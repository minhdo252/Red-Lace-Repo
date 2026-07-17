import math
import statistics

VLM_MEASUREMENT_SIGMA = 0.15  # nhiễu đo lường riêng của đọc ảnh tay — ước lượng ban đầu, hiệu chỉnh khi có nhiều dữ liệu VLM hơn
DEFAULT_CATEGORY_SIGMA = 0.3440220953127565  # fallback hiện tại của category 'food', dùng khi category/region chưa có row nào


def compute_sigma_data_vlm(pg_conn, category: str = "food", region: str = "Hanoi") -> float:
    """
    sigma_data cho item nguồn VLM ĐÃ QUA review (uncertain=False, giá qua sanity floor >=1.000đ).
    KHÔNG gọi hàm này cho item uncertain=True — item đó phải ở price_references_needs_review.

    MVP: category="food", region="Hanoi" mặc định — override khi mở rộng category/vùng khác.

    sigma_data = sqrt(sigma_category² + VLM_MEASUREMENT_SIGMA²)
    sigma_category (market spread giữa các quán, từ text sạch ShopeeFood) và
    VLM_MEASUREMENT_SIGMA (nhiễu đọc ảnh, VLM không có) là hai nguồn độc lập,
    không thay thế cho nhau — xem lại lý do trong thảo luận trước khi đổi hằng số.
    """
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT sigma_data FROM price_references WHERE category = %s AND region = %s",
            (category, region),
        )
        existing = [row[0] for row in cur.fetchall()]

    sigma_category = statistics.median(existing) if existing else DEFAULT_CATEGORY_SIGMA
    return math.sqrt(sigma_category**2 + VLM_MEASUREMENT_SIGMA**2)


def vlm_ready_items_to_postgres_rows(
    vlm_items: list[dict],
    pg_conn,
    region: str = "Hanoi",      # MVP: chỉ Hà Nội
    category: str = "food",     # MVP: khớp đúng giá trị thật đang dùng trong price_references
    normalize_item_name_fn=None,
    parse_price_vnd_fn=None,
) -> dict:
    """
    Nhận list item VLM (name_raw, price_raw, price_vnd, uncertain, notes),
    trả đúng shape 12 cột thật của price_references — chưa INSERT, chỉ chuẩn bị
    ready_rows (n=1, candidate mới) và needs_review (bị chặn, chưa fuse gì cả).

    Giả định: cả batch cùng 1 category + region (1 lần chụp = 1 menu). Nếu ảnh
    lẫn nhiều category, cần group theo category trước khi gọi hàm này.
    """
    ready_rows, needs_review = [], []
    sigma_data = compute_sigma_data_vlm(pg_conn, category=category, region=region)

    for item in vlm_items:
        if item.get("uncertain"):
            needs_review.append({**item, "reason": "vlm_uncertain"})
            continue

        price_vnd = parse_price_vnd_fn(item["price_raw"]) if parse_price_vnd_fn else item.get("price_vnd")
        if not price_vnd or price_vnd < 1000:
            needs_review.append({**item, "reason": "price_below_sanity_floor", "parsed_price_vnd": price_vnd})
            continue

        item_name = normalize_item_name_fn(item["name_raw"]) if normalize_item_name_fn else item["name_raw"]
        sum_y = math.log(price_vnd)
        n = 1

        ready_rows.append({
            "item_name": item_name,
            "region": region,
            "category": category,
            "mu_post": sum_y / n,
            "tau_post": sigma_data ** 2 / n,
            "sigma_data": sigma_data,
            "n": n,
            "sum_y": sum_y,
            "price_vnd": price_vnd,
        })

    return {"ready_rows": ready_rows, "needs_review": needs_review}


_PRICE_REFERENCES_COLUMNS = (
    "item_name", "region", "category", "price_vnd",
    "mu_post", "tau_post", "sigma_data", "n", "sum_y",
)


def push_ready_rows_to_postgres(ready_rows: list[dict], pg_conn) -> int:
    """
    INSERT thẳng ready_rows (output của vlm_ready_items_to_postgres_rows)
    vào price_references, dùng cùng pg_conn (cursor-style) như
    compute_sigma_data_vlm ở trên. Trả về số dòng đã insert.

    INSERT thuần, không merge/upsert: nếu bảng đã có sẵn 1 dòng cùng
    (item_name, region, category), dòng mới nằm cạnh chứ không gộp
    posterior — merge thật (Bayesian fusion vào dòng đã có) là
    app/modules/pricing.py::record_observation(), cần match qua Qdrant
    item_names trước, ngoài phạm vi hàm này.
    """
    if not ready_rows:
        return 0

    values = [tuple(row[col] for col in _PRICE_REFERENCES_COLUMNS) for row in ready_rows]
    placeholders = ", ".join(["%s"] * len(_PRICE_REFERENCES_COLUMNS))

    with pg_conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO price_references ({', '.join(_PRICE_REFERENCES_COLUMNS)}) "
            f"VALUES ({placeholders})",
            values,
        )
    pg_conn.commit()
    return len(values)