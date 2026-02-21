# Benchmark Selection Sheet Template (100 images)

Use this as a spreadsheet blueprint (Google Sheets or Excel) for selecting a diverse OCR benchmark set.

## 1) Target Counts

### By source type (fixed)

| Type | Target |
|---|---:|
| book | 50 |
| periodical | 25 |
| legal | 20 |
| misc | 5 |

### By difficulty (recommended)

| Difficulty | Target |
|---|---:|
| clean | 35 |
| medium | 40 |
| hard | 25 |

### Diversity minimums (recommended)

| Signal | Minimum count |
|---|---:|
| yellowed or dark paper | 30 |
| low contrast or faded print | 20 |
| skewed/warped geometry | 20 |
| table-heavy pages | 15 |
| multi-column pages | 15 |
| handwriting/stamps/seals | 10 |
| old-style or decorative fonts | 15 |

## 2) Sheet: `Pool` (candidate pool, 400-600 rows)

Use one row per candidate image.

| Column | Meaning |
|---|---|
| `candidate_id` | Unique ID in your sheet |
| `doc_id` | Document identifier (book/gazette/law ID) |
| `page_no` | Page number inside source document |
| `rel_path` | Relative image path |
| `type` | `book`, `periodical`, `legal`, `misc` |
| `difficulty` | `clean`, `medium`, `hard` |
| `paper_tone` | `white`, `yellowed`, `dark`, `mixed` |
| `contrast` | `high`, `medium`, `low` |
| `geometry` | `straight`, `mild_skew`, `strong_skew_warp` |
| `layout` | `single_col`, `multi_col`, `table_heavy`, `mixed` |
| `font_style` | `serif`, `sans`, `old_style`, `decorative` |
| `font_size` | `large`, `medium`, `small`, `tiny` |
| `artifacts` | `none`, `noise`, `bleed`, `stamp`, `handwriting`, `mixed` |
| `selected` | `TRUE/FALSE` |
| `notes` | Optional comments |

## 3) Sheet: `Selection` (final 100 rows)

Copy only selected rows here.

Add this extra column:
- `final_keep` (`TRUE/FALSE`) to support quick replacement without deleting rows.

## 4) Coverage Formulas (Google Sheets style)

Assume:
- `Selection!E:E` is `type`
- `Selection!F:F` is `difficulty`
- `Selection!G:G` is `paper_tone`
- `Selection!H:H` is `contrast`
- `Selection!I:I` is `geometry`
- `Selection!J:J` is `layout`
- `Selection!L:L` is `font_size`
- `Selection!M:M` is `artifacts`
- `Selection!N:N` is `final_keep`

### Core totals

- Total selected:
`=COUNTIF(Selection!N:N,TRUE)`

- Type counts:
`=COUNTIFS(Selection!E:E,"book",Selection!N:N,TRUE)`
`=COUNTIFS(Selection!E:E,"periodical",Selection!N:N,TRUE)`
`=COUNTIFS(Selection!E:E,"legal",Selection!N:N,TRUE)`
`=COUNTIFS(Selection!E:E,"misc",Selection!N:N,TRUE)`

- Difficulty counts:
`=COUNTIFS(Selection!F:F,"clean",Selection!N:N,TRUE)`
`=COUNTIFS(Selection!F:F,"medium",Selection!N:N,TRUE)`
`=COUNTIFS(Selection!F:F,"hard",Selection!N:N,TRUE)`

### Diversity checks

- Yellowed/dark paper:
`=COUNTIFS(Selection!G:G,"yellowed",Selection!N:N,TRUE)+COUNTIFS(Selection!G:G,"dark",Selection!N:N,TRUE)`

- Low contrast:
`=COUNTIFS(Selection!H:H,"low",Selection!N:N,TRUE)`

- Skew/warp:
`=COUNTIFS(Selection!I:I,"mild_skew",Selection!N:N,TRUE)+COUNTIFS(Selection!I:I,"strong_skew_warp",Selection!N:N,TRUE)`

- Table-heavy:
`=COUNTIFS(Selection!J:J,"table_heavy",Selection!N:N,TRUE)`

- Multi-column:
`=COUNTIFS(Selection!J:J,"multi_col",Selection!N:N,TRUE)`

- Tiny text:
`=COUNTIFS(Selection!L:L,"tiny",Selection!N:N,TRUE)`

- Handwriting/stamp artifacts:
`=COUNTIFS(Selection!M:M,"handwriting",Selection!N:N,TRUE)+COUNTIFS(Selection!M:M,"stamp",Selection!N:N,TRUE)+COUNTIFS(Selection!M:M,"mixed",Selection!N:N,TRUE)`

## 5) Sampling Rules

1. Cap per source document: max 2-3 pages.
2. Avoid near-duplicate neighboring pages unless needed for a specific edge case.
3. Fill hard cases early (do not leave them for the end).
4. Keep type quotas strict; use diversity quotas as optimization constraints.
5. Run a final manual pass to remove obvious duplicates in typography/layout.
