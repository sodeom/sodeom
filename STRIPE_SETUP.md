# Stripe Integration Setup - Day 5

This guide walks you through setting up Stripe payments for Sodeom Pro.

## Overview

When a user clicks Upgrade:
1. Stripe Checkout opens
2. User pays ($2.99/month or $19 lifetime)
3. Stripe calls your webhook
4. User `is_pro = True`
5. Ads removed + limits lifted

---

## Step 1: Create Stripe Account

1. Go to [https://dashboard.stripe.com](https://dashboard.stripe.com)
2. Sign up or log in
3. Complete account verification (for live payments)

---

## Step 2: Create Products & Prices

### Monthly Subscription ($2.99/month)

1. Go to **Products** → **Add Product**
2. Name: `Sodeom Pro Monthly`
3. Description: `Monthly subscription to Sodeom Pro with unlimited AI summaries and ad-free searching`
4. Pricing: **$2.99** → **Monthly**
5. Copy the **Price ID** (starts with `price_`)

### Lifetime Founding Member ($19 one-time)

1. Go to **Products** → **Add Product**
2. Name: `Sodeom Founding Member`
3. Description: `One-time payment for lifetime Pro access - early supporter offer`
4. Pricing: **$19** → **One-time**
5. Copy the **Price ID** (starts with `price_`)

---

## Step 3: Get API Keys

1. Go to **Developers** → **API Keys**
2. Copy:
   - **Publishable key** (starts with `pk_test_` or `pk_live_`)
   - **Secret key** (starts with `sk_test_` or `sk_live_`)

---

## Step 4: Set Up Webhook

### For Local Testing (Stripe CLI):

```bash
# Install Stripe CLI, then:
stripe login
stripe listen --forward-to localhost:9999/webhook
```

Copy the webhook signing secret shown (starts with `whsec_`)

### For Production:

1. Go to **Developers** → **Webhooks** → **Add endpoint**
2. Endpoint URL: `https://sodeom.com/webhook`
3. Select events to listen to:
   - `checkout.session.completed`
   - `customer.subscription.deleted` (for cancellations)
   - `invoice.payment_failed` (for failed payments)
4. Copy the **Signing secret** (starts with `whsec_`)

---

## Step 5: Configure Environment Variables

Create/update your `.env` file:

```bash
# Stripe Keys
STRIPE_SECRET_KEY=sk_test_xxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# Stripe Price IDs
STRIPE_PRO_MONTHLY_PRICE_ID=price_xxxxx
STRIPE_PRO_LIFETIME_PRICE_ID=price_xxxxx

# Flask Secret (for sessions)
FLASK_SECRET_KEY=your-random-secret-key-here
```

**IMPORTANT:** Never commit `.env` to git!

---

## Step 6: Test the Integration

### Test Card Numbers (Stripe Test Mode):

| Card Number | Result |
|-------------|--------|
| `4242 4242 4242 4242` | Success |
| `4000 0000 0000 0002` | Decline |
| `4000 0000 0000 9995` | Insufficient funds |

Use any future expiry date and any 3-digit CVC.

### Testing Flow:

1. Run your Flask app: `python app.py`
2. In another terminal: `stripe listen --forward-to localhost:9999/webhook`
3. Visit `http://localhost:9999/upgrade`
4. Click upgrade button, enter email
5. Complete test payment
6. Check webhook logs - should see `checkout.session.completed`
7. User should now be Pro!

---

## Step 7: Go Live

1. Switch to **Live Mode** in Stripe Dashboard
2. Get **Live** API keys (start with `pk_live_` and `sk_live_`)
3. Create products again in Live mode (prices are different!)
4. Update production `.env` with live keys
5. Set up production webhook at `https://sodeom.com/webhook`
6. Test with a real card (you can refund via Stripe Dashboard)

---

## Routes Implemented

| Route | Method | Purpose |
|-------|--------|---------|
| `/upgrade` | GET | Pricing page with Stripe checkout |
| `/create-checkout-session` | POST | Create Stripe checkout session |
| `/webhook` | POST | Handle Stripe webhook events |
| `/success` | GET | Payment success page |
| `/cancel` | GET | Payment cancelled page |
| `/check-pro/<email>` | GET | Check user's Pro status |
| `/upgrade-test` | POST | Test upgrade (bypass Stripe) |

---

## Database Schema (userdb.py)

The `users` table tracks:

```sql
id                  -- User ID
email               -- User email (unique)
is_pro              -- Pro status (0/1)
ai_count            -- Daily AI usage count
last_ai_reset       -- Last reset timestamp
stripe_customer_id  -- Stripe customer ID
subscription_id     -- Subscription ID
subscription_status -- active/cancelled/expired
subscription_type   -- monthly/lifetime
pro_expires_at      -- Expiry date (for monthly)
created_at          -- Account created
updated_at          -- Last updated
```

---

## Day 6 Preview

Coming next:
- Subscription cancellation handling
- Auto-expire monthly subscriptions
- Refund handling
- Abuse prevention
- Invoice reminders

---

## Troubleshooting

### "Payment system not configured"
- Check `.env` has `STRIPE_PUBLISHABLE_KEY` set

### Webhook not working
- Verify `STRIPE_WEBHOOK_SECRET` matches Stripe Dashboard
- Check Stripe CLI is forwarding to correct port
- Look at Flask logs for errors

### User not becoming Pro after payment
- Check webhook is receiving events
- Verify `user_id` in metadata matches your user
- Check Flask logs for database errors

### Need help?
- [Stripe Documentation](https://stripe.com/docs)
- [Stripe CLI](https://stripe.com/docs/stripe-cli)
- [Flask + Stripe Guide](https://stripe.com/docs/checkout/quickstart)
