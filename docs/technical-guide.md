# Connect Bright Data To Your Agent

This repository contains the [proof-safe-copy-angles skill](../skills/proof-safe-copy-angles/SKILL.md), not an application or collection service. Your agent retrieves actual sources through Bright Data in the current session, then uses the skill to write the business deliverable directly.

Connect your account using the [official hosted MCP quickstart](https://docs.brightdata.com/products/mcp-server/remote/quickstart). Keep credentials in your agent's secure connection settings, never in prompts, reports, or this repository. Check your account permissions and budget before collection.

The [official tool reference](https://docs.brightdata.com/products/mcp-server/tools) documents `scrape_as_markdown` for webpages and `search_engine` for discovery. Review/comment tools depend on your configured connection; inspect the actual available inputs and returned text rather than assuming fields, dates, or completeness. An already connected [supported Bright Data Scraper](https://docs.brightdata.com/scraping-automation/web-data-apis/web-scraper-api/overview) can also collect supported sources.

Make the skill available to your agent and use the single request in the [README](../README.md). If Bright Data access is missing, connect it before continuing. Do not substitute exports, generated examples, another provider, or an offline demonstration. Source quotes, actual URLs, capture times, and unknowns stay attached to the result.
