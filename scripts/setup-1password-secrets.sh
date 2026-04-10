#!/bin/bash
# Run this once to store Battleship pipeline secrets in macOS Keychain.
# You'll be prompted to paste each value.

SERVICE="polymarket-scanner"

echo "=== Battleship Pipeline — Keychain Setup ==="
echo ""

echo "1. Paste your OpenAI API key (optional if already stored for polymarket-scanner):"
read -s OPENAI_API_KEY
if [[ -n "$OPENAI_API_KEY" ]]; then
  security add-generic-password -U -s "$SERVICE" -a OPENAI_API_KEY -w "$OPENAI_API_KEY"
  echo "   ✅ OPENAI_API_KEY saved"
fi

echo ""
echo "2. Paste your xAI API key (optional if already stored for polymarket-scanner):"
read -s XAI_API_KEY
if [[ -n "$XAI_API_KEY" ]]; then
  security add-generic-password -U -s "$SERVICE" -a XAI_API_KEY -w "$XAI_API_KEY"
  echo "   ✅ XAI_API_KEY saved"
fi

echo ""
echo "3. SMTP host (e.g. smtp.mail.me.com for iCloud, smtp.gmail.com for Gmail):"
read SMTP_HOST

echo "4. SMTP username / sending email address:"
read SMTP_USER

echo "5. SMTP password (app-specific password — NOT your account password):"
echo "   iCloud: appleid.apple.com → Sign-In & Security → App-Specific Passwords"
echo "   Gmail:  myaccount.google.com → Security → 2-Step → App passwords"
read -s SMTP_PASS

security add-generic-password -U -s "$SERVICE" -a SMTP_HOST -w "$SMTP_HOST"
security add-generic-password -U -s "$SERVICE" -a SMTP_USER -w "$SMTP_USER"
security add-generic-password -U -s "$SERVICE" -a SMTP_PASS -w "$SMTP_PASS"
echo "   ✅ SMTP credentials saved"

echo ""
echo "5. Stripe secret key (sk_live_... or sk_test_... — press Enter to skip):"
read -s STRIPE_KEY
if [ -n "$STRIPE_KEY" ]; then
  op item create \
    --category "API Credential" \
    --title "Stripe" \
    --vault "Private" \
    "api-key=$STRIPE_KEY"
  echo "   ✅ Stripe key saved"
else
  echo "   (skipped — Stripe not configured)"
fi

echo ""
echo "=== Setup complete. Run the pipeline to verify: ==="
echo "python3 /Users/will/Obsidian-Vaults/BattleShip-Vault/scripts/battleship_pipeline.py"
