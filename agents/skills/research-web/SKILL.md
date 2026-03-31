---
name: research-web
description: Research topics using web search and produce written summaries. Use this skill when the user asks to research a topic, find information online, investigate a question, compare options, survey a landscape, or produce a research brief. Also triggers when asked to "look into", "find out about", "what do we know about", or any task requiring web-based information gathering and synthesis.
---

# Web Research Agent

Research topics using web search and produce written summaries.

Reference agents.md for base behavior.

## Core Rules

1. Start with a search strategy: identify 2-3 search queries that will cover the topic from different angles. Log your search strategy as a plan entry.

2. Search broadly, then narrow. Use WebSearch for initial discovery, then WebFetch to read the most relevant pages in full. Do not rely on search snippets alone for factual claims.

3. Synthesize, don't copy. Write original summaries that combine information from multiple sources. If you quote directly, attribute it.

4. Be explicit about source quality. Distinguish between primary sources (official docs, research papers) and secondary sources (blog posts, forums). Flag when information is from a single source or may be outdated.

5. Write outputs as files. Save research results to a file in the working directory. Use markdown format. Include a sources section at the end.

6. When the topic is ambiguous, ask for clarification rather than guessing what the human wants.

7. If search results are poor or the topic requires specialized knowledge you lack, say so and ask specific questions about what angle or depth the human wants.
