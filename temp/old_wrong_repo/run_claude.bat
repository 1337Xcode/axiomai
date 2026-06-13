@echo off
setlocal

echo ======================================================
echo    Kimchi.dev Claude Code Setup  ^|  Vibe Mode ON
echo ======================================================
echo.
echo  Models:  kimi-k2.6 (main)  ^|  minimax-m2.7 (fast)
echo  Context: 260K  ^|  No fixed rate limits
echo ======================================================
echo.

:: Prompt for Kimchi API key (get one free at app.kimchi.dev/settings)
set /p KIMCHI_KEY="Enter your Kimchi API Key: "

if "%KIMCHI_KEY%"=="" (
    echo [ERROR] API key cannot be empty. Restart and try again.
    pause
    exit /b
)

echo.
echo [1/4] Routing Claude Code through Kimchi's Anthropic-compatible endpoint...

:: Kimchi's drop-in Anthropic endpoint — no other changes needed in Claude Code
setx ANTHROPIC_AUTH_TOKEN "%KIMCHI_KEY%" >nul
setx ANTHROPIC_BASE_URL "https://llm.kimchi.dev/anthropic" >nul

echo [2/4] Pinning models...

:: kimi-k2.6 = best agentic coding model (260K ctx, image analysis, latest)
:: minimax-m2.7 = fast + cheap for background/subagent tasks
setx ANTHROPIC_MODEL "kimi-k2.6" >nul
setx ANTHROPIC_DEFAULT_OPUS_MODEL "kimi-k2.6" >nul
setx ANTHROPIC_DEFAULT_SONNET_MODEL "kimi-k2.6" >nul
setx ANTHROPIC_DEFAULT_HAIKU_MODEL "minimax-m2.7" >nul

echo [3/4] Tuning for max vibe coding performance...

:: Subagent (background tasks, tool calls) uses the fast model to save cost
setx CLAUDE_CODE_SUBAGENT_MODEL "minimax-m2.7" >nul

:: Auto-compact kicks in when context hits 80% of 260K — keeps long sessions alive
setx CLAUDE_CODE_AUTO_COMPACT_WINDOW "200000" >nul

:: Push response length as far as it'll go (kimi-k2.6 supports 32K output)
setx CLAUDE_CODE_MAX_OUTPUT_TOKENS "32000" >nul

:: Skip telemetry pings — cleaner, faster, no background noise
setx CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC "1" >nul

:: Extended timeout for long generations and deep refactors
setx API_TIMEOUT_MS "600000" >nul

echo [4/4] Launching a new session with everything loaded...
echo.
echo ======================================================
echo  Ready. Kimi K2.6 is your brain. MiniMax M2.7 does
echo  the grunt work. Auto-compact keeps long runs alive.
echo.
echo  Grab a free API key: https://app.kimchi.dev/settings
echo  Docs: https://docs.kimchi.dev/docs/claude-code
echo ======================================================
echo.

start cmd /k "echo Launching Claude Code via Kimchi... && claude"

echo Setup done. You can close this window.
pause