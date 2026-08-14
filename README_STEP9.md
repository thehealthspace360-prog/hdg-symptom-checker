# HDG Step 9 — Article Index Updater / Validator

This is the **semi-automatic** version of Step 9.

It is deliberately designed **not to silently rewrite the live index**. The tool finds problems and new pages, then gives you a review report.

## Files to add to the GitHub repository

Put these beside `HDG_Public_Article_Index.txt`:

- `hdg_index_validator.py`
- `hdg_index_config.json`
- `.github/workflows/validate-hdg-index.yml`

Your live chatbot files remain unchanged.

## What it checks

The validator checks:

- missing TITLE / LANGUAGE / CATEGORY / EMERGENCY / URL / KEYWORDS;
- duplicate article numbers;
- duplicate URLs;
- invalid LANGUAGE values;
- invalid EMERGENCY values;
- strong English/Pidgin metadata mismatches;
- suspiciously thin keywords;
- a small set of high-confidence category mismatches;
- sitemap URLs that are not yet in the article index;
- index URLs that are no longer in the sitemap.

For new URLs it creates `HDG_New_Article_Stubs.txt`, with `REVIEW` in fields that should still be checked by a human.

## Why it does not auto-publish

`LANGUAGE`, `CATEGORY`, `KEYWORDS`, and especially `EMERGENCY` can affect Ask HDG behaviour.

The validator may infer a likely language for an obvious `pidgin-english` URL, but it **does not automatically approve clinical metadata**.

That avoids turning a sitemap crawler into an unreviewed clinical publishing system.

## GitHub Actions

The included workflow:

- can be run manually from **GitHub → Actions → Validate HDG Article Index → Run workflow**;
- also runs once a week;
- downloads the current website sitemap;
- uploads a report artifact called **HDG-index-check**.

Nothing is committed automatically.

## Files produced

Inside the Action artifact:

- `HDG_Index_Validation_Report.md` — easiest report to read;
- `HDG_Index_Validation_Report.json` — structured version;
- `HDG_New_Article_Stubs.txt` — candidate records for new sitemap URLs.

## Manual local run

```bash
python hdg_index_validator.py --index HDG_Public_Article_Index.txt
```

Metadata only:

```bash
python hdg_index_validator.py --index HDG_Public_Article_Index.txt --metadata-only
```

## Recommended workflow

1. Publish new HDG articles.
2. Run the GitHub Action.
3. Download `HDG-index-check`.
4. Review new stubs and any metadata flags.
5. Add/correct only the reviewed records in `HDG_Public_Article_Index.txt`.
6. Commit the corrected public index.
7. Test Ask HDG with the new topics.

Later, once this process proves reliable, we can move from **semi-automatic review** to **automatic pull-request generation** without auto-publishing unreviewed clinical metadata.
