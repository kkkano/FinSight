import json
import re
from llm_service import call_llm
from tools import (
    get_stock_price, get_company_news, get_company_info, search,
    get_market_sentiment, get_economic_events, get_performance_comparison,
    analyze_historical_drawdowns, get_current_datetime
)
from datetime import datetime

SYSTEM_PROMPT = """You are a Chief Investment Officer (CIO) at a major hedge fund. Your job is to produce COMPREHENSIVE, ACTIONABLE investment reports.

YOUR MISSION:
Gather real-time data step-by-step, then write a DETAILED professional report (minimum 800 words) with specific insights, recommendations, and risk analysis.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TWO-PHASE WORKFLOW:

**PHASE 1: DATA COLLECTION (Use Thought-Action cycle)**

Required steps for ANY query:
1. get_current_datetime - ALWAYS start here
2. search - Get market context and recent developments
3. Relevant analysis tools (performance, sentiment, drawdowns, etc.)
4. search again - Look for recent news with current date

**PHASE 2: COMPREHENSIVE REPORT (Use "Final Answer:")**

Once you have 4-6 observations, write your final report.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY REPORT STRUCTURE:

Final Answer:

# [Investment Name] - Professional Analysis Report
*Report Date: [Use actual date from get_current_datetime]*

## EXECUTIVE SUMMARY (2-3 sentences)
High-conviction summary with clear recommendation (BUY/HOLD/SELL).

## CURRENT MARKET POSITION
- Current price/level and recent performance
- Year-to-date and 1-year returns
- Comparison with benchmarks (if applicable)
- Key technical levels (52-week high/low, support/resistance)

## MACRO ENVIRONMENT & CATALYSTS
- Current economic conditions (inflation, interest rates, Fed policy)
- Major upcoming events (earnings, FOMC meetings, economic data releases)
- Geopolitical factors (elections, trade policies, conflicts)
- Sector-specific trends affecting this investment
- Recent major news or developments (be specific with dates and details)

## FUNDAMENTAL ANALYSIS (for stocks/companies)
- Business model and competitive advantages
- Revenue streams and profit margins
- Management quality and recent decisions
- Industry position and market share
- Growth prospects and expansion plans

## TECHNICAL & SENTIMENT ANALYSIS
- Current market sentiment (Fear & Greed Index if available)
- Trading volume and momentum indicators
- Institutional ownership and insider activity
- Social media sentiment and retail interest

## RISK ASSESSMENT
- Historical volatility and maximum drawdowns
- Key risks specific to this investment
- Correlation with broader market
- Black swan scenarios and tail risks
- What could go wrong with this investment?

## INVESTMENT STRATEGY & RECOMMENDATIONS

**Primary Recommendation:** [BUY / SELL / HOLD]
**Confidence Level:** [High / Medium / Low]
**Time Horizon:** [Short-term (0-6mo) / Medium-term (6-18mo) / Long-term (18mo+)]

**Entry Strategy:**
- Ideal entry price/level
- Position sizing recommendation
- Dollar-cost averaging vs lump sum

**Risk Management:**
- Stop-loss levels
- Take-profit targets
- Portfolio allocation (what % of portfolio)
- Hedging strategies if applicable

**Exit Strategy:**
- When to take profits
- When to cut losses
- Rebalancing triggers

## OUTLOOK & PRICE TARGETS

**Bull Case Scenario:**
- What needs to happen
- Potential upside percentage
- Timeline

**Base Case Scenario:**
- Most likely outcome
- Expected return
- Timeline

**Bear Case Scenario:**
- Warning signs to watch
- Potential downside
- Timeline

## KEY TAKEAWAYS (3-5 bullet points)
- Most important insights
- Critical factors to monitor
- Action items for investors

## IMPORTANT EVENTS TO MONITOR
- Upcoming earnings reports
- Fed meetings and economic data releases
- Regulatory decisions
- Competitor actions
- Industry conferences

---
*Disclaimer: This analysis is for informational purposes only and does not constitute financial advice. All investment decisions should be made in consultation with a qualified financial advisor. Past performance does not guarantee future results.*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE TOOLS:

1. get_current_datetime -> {"tool_name": "get_current_datetime", "tool_input": {}}
2. search -> {"tool_name": "search", "tool_input": {"query": "your query"}}
3. get_company_info -> {"tool_name": "get_company_info", "tool_input": {"ticker": "AAPL"}}
4. get_stock_price -> {"tool_name": "get_stock_price", "tool_input": {"ticker": "AAPL"}}
5. get_company_news -> {"tool_name": "get_company_news", "tool_input": {"ticker": "AAPL"}}
6. get_performance_comparison -> {"tool_name": "get_performance_comparison", "tool_input": {"tickers": {"Name": "TICK"}}}
7. analyze_historical_drawdowns -> {"tool_name": "analyze_historical_drawdowns", "tool_input": {"ticker": "^IXIC"}}
8. get_market_sentiment -> {"tool_name": "get_market_sentiment", "tool_input": {}}
9. get_economic_events -> {"tool_name": "get_economic_events", "tool_input": {}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL GUIDELINES:

1. **BE SPECIFIC**: Include actual dates, numbers, percentages, and names
2. **BE COMPREHENSIVE**: Your report should be 800+ words minimum
3. **BE ACTIONABLE**: Give concrete buy/sell/hold recommendations with reasoning
4. **USE ALL DATA**: Reference every observation you collected in your report
5. **BE CURRENT**: Always mention recent developments (last 30 days)
6. **NO GENERIC ADVICE**: Avoid vague statements like "do your research"
7. **SHOW YOUR WORK**: Explain WHY you reached each conclusion

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES:

**Good Data Collection:**
Thought: I need to start by getting the current date.
Action:
```json
{"tool_name": "get_current_datetime", "tool_input": {}}
```

**Good Final Report Opening:**
Final Answer:
# Nasdaq Composite Index - Professional Analysis Report
*Report Date: October 12, 2025*

## EXECUTIVE SUMMARY
The Nasdaq Composite Index shows moderate bullish momentum as of October 2025, supported by strong tech earnings and dovish Fed signals. Based on current technical setup and macro tailwinds, I recommend a HOLD position with selective buying opportunities in pullbacks. The index has recovered 87% from the 2022 bear market lows, but faces near-term resistance at the 15,800 level...
[Continue with all sections, being VERY detailed and specific]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REMEMBER:

"Final Answer:" is NOT a tool - it's a text prefix to start your report
Collect 4-6 observations before writing your report
Your report must be detailed, specific, and actionable
Include concrete numbers, dates, and recommendations

Now begin your analysis.
"""

class Agent:
    def __init__(self, provider="gemini_proxy", model="gemini-2.5-flash-preview-05-20"):
        self.provider = provider
        self.model = model
        self.tools = {
            "get_stock_price": get_stock_price,
            "get_company_news": get_company_news,
            "get_company_info": get_company_info,
            "search": search,
            "get_market_sentiment": get_market_sentiment,
            "get_economic_events": get_economic_events,
            "get_performance_comparison": get_performance_comparison,
            "analyze_historical_drawdowns": analyze_historical_drawdowns,
            "get_current_datetime": get_current_datetime
        }
        self.consecutive_errors = 0
        self.observations_count = 0

    def _clean_json_response(self, response_str: str) -> str:
        response_str = re.sub(r'```json\s*', '', response_str)
        response_str = re.sub(r'```\s*', '', response_str)
        return response_str.strip()

    def _extract_tool_input(self, tool_name: str, tool_input):
        if tool_input is None or tool_input == {}:
            return None
        if isinstance(tool_input, dict):
            if tool_name == "search":
                return tool_input.get("query", "")
            elif tool_name in ["get_stock_price", "get_company_news", "get_company_info", "analyze_historical_drawdowns"]:
                return tool_input.get("ticker", "")
            elif tool_name == "get_performance_comparison":
                return tool_input.get("tickers", {})
        return tool_input

    def _get_timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def run(self, user_query: str, max_steps: int = 20):
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        print("=" * 70)
        print("PROFESSIONAL FINANCIAL ANALYSIS AGENT")
        print("=" * 70)
        print(f"Query: {user_query}")
        print(f"Started: {self._get_timestamp()}\n")

        system_prompt_with_date = f"{SYSTEM_PROMPT}\nTODAY'S DATE IS {current_date}. You MUST use this exact date in your analysis and report."
        
        messages = [{"role": "system", "content": system_prompt_with_date}]
        messages.append({"role": "user", "content": f"Today is {current_date}. Please analyze: {user_query}"})

        for step in range(max_steps):
            print("-" * 70)
            print(f"Step {step + 1}/{max_steps}")
            print("-" * 70)

            response_str = call_llm(self.provider, self.model, messages)
            if response_str is None:
                print("LLM service unavailable")
                return "Sorry, the LLM service is currently unavailable."

            if "Final Answer:" in response_str:
                final_answer = response_str.split("Final Answer:")[-1].strip()
                
                if "Report Date:" in final_answer and current_date not in final_answer:
                    date_correction_prompt = f"""Your report contains an incorrect date. Today is {current_date}. 
                    Regenerate your ENTIRE report using EXACTLY '{current_date}' as the report date. 
                    DO NOT use any other date format like 'May 16, 2024'.
                    The report date line should read: *Report Date: {current_date}*"""
                    
                    messages.append({"role": "assistant", "content": response_str})
                    messages.append({"role": "user", "content": date_correction_prompt})
                    
                    corrected_response = call_llm(self.provider, self.model, messages)
                    if corrected_response and "Final Answer:" in corrected_response:
                        final_answer = corrected_response.split("Final Answer:")[-1].strip()
                
                print(f"\n{'='*70}")
                print("PROFESSIONAL ANALYSIS REPORT GENERATED")
                print(f"{'='*70}\n")
                print(final_answer)

                word_count = len(final_answer.split())
                print(f"\nReport Statistics:")
                print(f"   - Word Count: {word_count}")
                print(f"   - Data Points Used: {self.observations_count}")

                if word_count < 300:
                    print("   Warning: Report seems short. You may want to re-run for more detail.")

                return final_answer
            
            try:
                thought_pattern = r"Thought:\s*(.+?)(?=\nAction:)"
                action_pattern = r"Action:\s*```json\s*(\{.+?\})\s*```"
                thought_match = re.search(thought_pattern, response_str, re.DOTALL | re.IGNORECASE)
                action_match = re.search(action_pattern, response_str, re.DOTALL | re.IGNORECASE)

                if not action_match:
                    action_pattern_alt = r"Action:\s*(\{[^{}]+(?:\{[^}]+\}[^{}]*)*\})"
                    action_match = re.search(action_pattern_alt, response_str, re.DOTALL)

                if not thought_match:
                    raise ValueError("Missing 'Thought:' section")
                if not action_match:
                    raise ValueError("Missing 'Action:' JSON block")

                thought = thought_match.group(1).strip()
                action_json_str = self._clean_json_response(action_match.group(1))
                action = json.loads(action_json_str)

                tool_name = action.get("tool_name")
                tool_input = action.get("tool_input", {})

                if not tool_name:
                    raise ValueError("Missing 'tool_name' in Action")

                if tool_name.lower() in ["final answer", "final_answer", "finalanswer"]:
                    print("Detected incorrect use of 'Final Answer' as tool")
                    messages.append({"role": "assistant", "content": response_str})
                    messages.append({"role": "user", "content": """CRITICAL ERROR: "Final Answer" is NOT a tool!
When ready to write your comprehensive report, simply write:
Final Answer:
# [Title] - Professional Analysis Report
*Report Date: [date]*
## EXECUTIVE SUMMARY
[Your detailed summary here...]
[Continue with ALL required sections...]
Do NOT use "Final Answer" in the Action JSON!"""})
                    continue

                print(f"Thought: {thought[:150]}{'...' if len(thought) > 150 else ''}")
                print(f"Action: {tool_name}")
                self.consecutive_errors = 0

            except (json.JSONDecodeError, ValueError) as e:
                self.consecutive_errors += 1
                print(f"Parse Error ({self.consecutive_errors}/3): {e}")

                if self.consecutive_errors >= 3:
                    print("\nToo many errors. Generating report with available data...")
                    messages.append({"role": "user", "content": f"""You've made {self.consecutive_errors} format errors.
Please now write your comprehensive Final Answer report based on all the data you've gathered about '{user_query}'.
Remember to include:

Executive summary with clear recommendation
Current market position
Macro environment and recent news
Risk assessment
Investment strategy with entry/exit points
Bull/base/bear case scenarios

Make it detailed (800+ words) and actionable."""})
                    continue
                messages.append({"role": "assistant", "content": response_str})
                messages.append({"role": "user", "content": f"""Format Error: {e}
Use this format:
Thought: [your reasoning]
Action:
```json
{{"tool_name": "tool_name", "tool_input": {{...}}}}
```
Or if you have enough data (4+ observations), write:
Final Answer:
# [Title] - Professional Analysis Report
[Your comprehensive report here...]"""})
                continue

            if tool_name not in self.tools:
                observation = f"Unknown tool '{tool_name}'. Available: {', '.join(self.tools.keys())}"
                print(observation)
            else:
                try:
                    actual_input = self._extract_tool_input(tool_name, tool_input)

                    if tool_name in ["get_current_datetime", "get_market_sentiment", "get_economic_events"]:
                        print(f"Executing: {tool_name}()")
                        observation = self.tools[tool_name]()
                    else:
                        print(f"Executing: {tool_name}({actual_input})")
                        observation = self.tools[tool_name](actual_input)
                        if "error" not in observation.lower() and "unavailable" not in observation.lower():
                            self.observations_count += 1
                            print(f"Valid Observation #{self.observations_count}: {observation[:100]}...")
                        else:
                            print("Skipped invalid obs.")
                    self.observations_count += 1

                    display_obs = observation[:250] + "..." if len(observation) > 250 else observation
                    print(f"Result: {display_obs}")

                    if "error" in observation.lower() or "unavailable" in observation.lower():
                        print("Tool returned an error - AI will adapt strategy")

                except Exception as e:
                    observation = f"Tool error: {str(e)}"
                    print(observation)

            print()

            messages.append({
                "role": "assistant",
                "content": f"Thought: {thought}\nAction:\n```json\n{json.dumps(action, indent=2)}\n```"
            })
            messages.append({"role": "user", "content": f"Observation: {observation}"})

            if self.observations_count == 4:
                print("Hint: You have 4 observations. You can start writing your report soon.\n")
            elif self.observations_count >= 6:
                print("Strong Hint: You have 6+ observations. You should write your comprehensive Final Answer report now.\n")

        print(f"\nMaximum steps reached ({max_steps}).")
        print("Forcing comprehensive report generation...\n")

        final_prompt = f"""You have reached the maximum number of steps ({max_steps}).
Today is {current_date}.
You MUST now provide your Final Answer - a comprehensive professional investment report about '{user_query}'.
Based on ALL the observations you've gathered, write a DETAILED report (minimum 2000 words) that includes:

Executive Summary with clear BUY/SELL/HOLD recommendation
Current market position and recent performance
Macro environment (Fed policy, interest rates, economic data, recent major events)
Risk assessment with specific scenarios
Investment strategy with entry/exit points and position sizing
Bull/Base/Bear case scenarios with timelines
Key events to monitor (earnings, Fed meetings, etc.)

CRITICALLY IMPORTANT: Your report MUST use today's date: {current_date}
The report date line should be: *Report Date: {current_date}*
DO NOT use any other date format like 'May 16, 2024'.

Be SPECIFIC with dates, numbers, and actionable recommendations. Use all the data you collected.
Use search fallbacks for any failed tools.
Write your report now."""
        messages.append({"role": "user", "content": final_prompt})
        final_response = call_llm(self.provider, self.model, messages)

        if final_response and "Final Answer:" in final_response:
            final_answer = final_response.split("Final Answer:")[-1].strip()
            
            if "Report Date:" in final_answer and current_date not in final_answer:
                date_patterns = [
                    r"Report Date: ([A-Za-z]+ \d{1,2}, \d{4})",
                    r"\*Report Date: ([^*]+)\*",
                    r"Date: ([A-Za-z]+ \d{1,2}, \d{4})"
                ]
                
                for pattern in date_patterns:
                    final_answer = re.sub(pattern, f"*Report Date: {current_date}*", final_answer)
            
            print(f"\n{'='*70}")
            print("PROFESSIONAL ANALYSIS REPORT (Generated)")
            print(f"{'='*70}\n")
            print(final_answer)

            word_count = len(final_answer.split())
            print(f"\nFinal Report Statistics:")
            print(f"   - Word Count: {word_count}")
            print(f"   - Data Points Collected: {self.observations_count}")

            return final_answer

        return f"Unable to generate comprehensive report for '{user_query}'. Please try again with a more specific question."