# Part 4: Knowledge Base Complete Analysis

> **For AI Assistants**: Part 4 of 5. This section covers the `kb/` folder in depth.

## Table of Contents
1. [KB Structure Overview](#kb-structure-overview)
2. [policy.md - Master Policy](#policymd---master-policy)
3. [documents/ - 698 KB Articles](#documents---698-kb-articles)
4. [Document Categories](#document-categories)
5. [Document Format & Schema](#document-format--schema)
6. [embeddings.json - Cache File](#embeddingsjson---cache-file)

---

## KB Structure Overview

```
kb/
├── policy.md              # Master CS agent policy (62 lines)
├── documents/             # 698 JSON articles
│   ├── doc_bank_accounts_bank_accounts_(general)_001.json
│   ├── doc_bank_accounts_bank_accounts_(general)_002.json
│   ├── ... (696 more files)
│   └── doc_credit_cards_credit_card_account_logistics_0xx.json
└── embeddings.json        # Generated cache (gitignored)
```

---

## policy.md - Master Policy

**Location:** `kb/policy.md`
**Size:** 62 lines (5,599 bytes)

**Full Contents:**
```markdown
# Rho-Bank Customer Service Policy

You are a helpful customer service agent for Rho-Bank.
Your goal is to help customers by searching the knowledge base and providing accurate information.

## Guidelines

1. Do not make up policies, information or actions that you can take on behalf of the user. All instructions will be found here or in the knowledge base. If you cannot find relevant information, let the user know. 
2. Do not ask for any documentation, receipts... from the customer unless it states very clearly in the knowledge base how to process it, and whether you're allowed to do so. 
3. Be polite and professional
4. If you need the current time, always use the get_current_time() tool. Do not make up or assume the current time. 
5. Generally, if the issue cannot be resolved or is outside your capabilities, ask the user whether they would like to be transferred to a human agent. If they do, invoke the appropriate transfer_to_human_agents tool. Do this only if you absolutely have to, and you are sure that there are no potential actions you can take as specified in the knowledge base, or in your policy. Do not transfer without asking the user first. This guidance may be overridden by specific scenario-based transfer guidance in the knowledge base. 
6. If an issue falls within your capabilities and the user still wants to be transferred to a human agent, kindly inform the user that you can help them, and try to help them first. If the user asks for a human agent 4 times, then you may invoke the transfer_to_human_agents tool. This guidance may be overridden by specific scenario-based transfer guidance in the knowledge base. 
7. Do not give intermediate responses to users while processing that would give away internal rho-bank information/policies. 



## Additional Instructions

### Discoverable Tools

#### Giving Discoverable Tools to Users
The knowledge base may contain instructions that indicate certain actions should be performed by the user themselves rather than by you. These are called "user discoverable tools." A user discoverable tool is a tool that you provide to the user so they can execute it on their own (e.g., through a customer portal or app).

**When to give user discoverable tools:**
-  Only give a tool when the user would like to perform an action, and the knowledge base explicitly has a tool that allows the user to perform this action (e.g., "to do X, have the user call tool_name(args)"). IMPORTANT: Do not unlock tools that you do not plan on giving to the user and actually using: this causes issues in database logging.
- You must search the knowledge base to find tools that you can give. Do not invent or guess user discoverable tools 
- Only use tool names and arguments discovered in the knowledge base

**How to give a tool:**
- Use the `give_discoverable_user_tool(discoverable_tool_name)` function
- Provide the exact tool name  as specified in the knowledge base
- Explain to the user what the tool does and how to use it, and what arguments to provide. Just explaining isn't enough, you must use the `give_discoverable_user_tool(discoverable_tool_name)` function.

#### Unlocking and Using Agent Discoverable Tools
The knowledge base may contain references to specialized internal tools that you can unlock and use. These are called "agent discoverable tools." Unlike regular tools which are always available, these tools must be explicitly unlocked after discovering them in the knowledge base.

**When to use agent discoverable tools:**
- Only unlock a tool when the knowledge base explicitly mentions it (e.g., "use tool_name to perform X"), and do not unlock tools you do not plan on using.
- You must search the knowledge base to find tools that you can unlock. Do not invent or guess tool names - only use tool names discovered in the knowledge base.

**How to use agent discoverable tools:**
1. First, unlock the tool using `unlock_discoverable_agent_tool(agent_tool_name)` with the exact tool name from the knowledge base: you must unlock the tool before using it to get information on the proper params. IMPORTANT: Do not unlock tools that you do not plan on actually using: this causes issues in database logging.
2. Then, call the tool using `call_discoverable_agent_tool(agent_tool_name, arguments)` with the required arguments
3. The unlock step is required before calling - you cannot call a tool that hasn't been unlocked

### Authenticating Users

Generally, for any scenario involving accessing customer information in internal databases, you must first verify their identify before proceeding. No need to verify more than once in a single conversation. You should ONLY verify a user's identity if you need to access or modify their customer information in internal databases on their behalf.

Here are some concrete examples:
* Looking up account balances, transaction history, referral history...
* Changing account settings (e.g., address, phone number, email)
* Closing an account
* Adding or removing authorized users
* Requesting information about specific transactions
* Discussing specific loan or credit details
* Filing a dispute on behalf of the user

To verify the identity of the user, call the appropriate read tools, and ensure that they are able to give correctly any 2 out of the following values: date of birth, email, phone number, address. Knowing full name or userID is not enough to verify. After verification, you must call the verification logging tool to properly log the information into the verification records. Do not leak any information about the user before they are verified.
```

### Policy Key Points

| Section | Key Rules |
|---------|-----------|
| **Guidelines** | Don't make up policies; don't ask for docs unless KB says so; be polite; use `get_current_time()` tool; transfer to human only when necessary (ask first, or after 4 requests) |
| **User Discoverable Tools** | Tools the USER should call (via their personal agent). Use `give_discoverable_user_tool(tool_name)` to grant. Must be from KB, not invented. |
| **Agent Discoverable Tools** | Tools the CS agent can unlock and use. Must call `unlock_discoverable_agent_tool(tool_name)` before `call_discoverable_agent_tool(tool_name, args)` |
| **Authentication** | Verify identity (2 of: DOB, email, phone, address) before accessing/modifying customer data. Log verification. |

### Tools Referenced in Policy

| Tool | Type | Purpose |
|------|------|---------|
| `get_current_time()` | Standard | Get current time (don't hallucinate) |
| `transfer_to_human_agents` | Standard | Escalate to human CS |
| `give_discoverable_user_tool(tool_name)` | User tools | Grant tool to user |
| `unlock_discoverable_agent_tool(tool_name)` | Agent tools | Unlock internal tool |
| `call_discoverable_agent_tool(tool_name, args)` | Agent tools | Call unlocked tool |

---

## documents/ - 698 KB Articles

### Filename Pattern
```
doc_{CATEGORY}_{SUBCATEGORY}_{NNN}.json
```

**Examples:**
- `doc_bank_accounts_bank_accounts_(general)_001.json`
- `doc_business_checking_accounts_beige_006.json`
- `doc_credit_cards_credit_card_account_logistics_004.json`

### Document Categories (from filename analysis)

| Category | Subcategories | Count (approx) |
|----------|--------------|----------------|
| `bank_accounts` | `bank_accounts_(general)` | ~50 |
| `business_checking_accounts` | `beige` | ~10 |
| `credit_cards` | `credit_card_account_logistics`, others | ~100+ |
| ... | ... | ... |
| **Total** | | **698** |

### Document Format & Schema

**Every document follows this exact structure:**
```json
{
  "id": "string",
  "title": "string",
  "content": "string (markdown)"
}
```

**Field Descriptions:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | String | Unique identifier (matches filename without extension) |
| `title` | String | Human-readable title |
| `content` | String | Markdown-formatted content with procedures |

### Example Documents

#### Example 1: Opening Personal Checking
**File:** `doc_bank_accounts_bank_accounts_(general)_001.json`

```json
{
  "id": "doc_bank_accounts_bank_accounts_(general)_001",
  "title": "Internal: Opening Personal Checking Accounts",
  "content": "## Eligibility Requirements\n\nTo open a personal checking account, ensure all of the following are true:\n1. The customer is verified.\n2. The customer is at least 18 years old.\n3. The customer does not exceed 4 personal checking accounts.\n4. The customer has no checking accounts closed for cause in the past 6 months.\n\n## Opening Procedure\n\n1. Verify customer identity.\n2. Check eligibility requirements listed above.\n3. Confirm the customer's desired account_class selection.\n   - Personal checking account_class options must use the full official name ending with 'Account' (e.g., 'Blue Account', 'Green Account (checking)').\n4. Use open_bank_account_4821 to open the account."
}
```

**Key Information:**
- Eligibility: verified, 18+, <4 accounts, no recent closures
- Tool mentioned: `open_bank_account_4821`
- Account class format: full name ending with 'Account'

#### Example 2: Opening Personal Savings
**File:** `doc_bank_accounts_bank_accounts_(general)_002.json`

```json
{
  "id": "doc_bank_accounts_bank_accounts_(general)_002",
  "title": "Internal: Opening Personal Savings Accounts",
  "content": "## Scope and Focus\n\nProcedure for opening personal savings accounts. Eligibility requirements: 1) Customer must be verified, 2) Customer must already have at least one active Rho-Bank checking account, 3) Cannot have more than 5 personal savings accounts, 4) Must not have any accounts in collections or with negative balances, 5) Must have held their checking account for at least 14 days. Steps: 1) Verify customer identity, 2) Check eligibility requirements, 3) Confirm account selection with customer, 4) Use open_bank_account_4821 to open the account (note: account_class must use the full official name ending with 'Account', e.g., 'Silver Plus Account', 'Gold Account'), 5) Ask the customer if they would like you to transfer the opening deposit from their checking account now. If yes, use transfer_funds_between_bank_accounts_7291 to transfer the required amount. If no, inform them they have 30 days to fund the account (via internal transfer or external deposit) or the account will be closed.\n\n## Eligibility Requirements (Internal Checklist)\n\nConfirm all of the following before proceeding:\n- Customer identity is verified in our systems.\n- Customer has at least one active Rho-Bank checking account.\n- Customer currently holds fewer than 5 personal savings accounts.\n- Customer has no accounts in collections and no negative balances.\n- The customer's checking account tenure is at least 14 days.\n\nDo not proceed if any item above is not met.\n\n## Step-by-Step Procedure\n\n1) Verify identity\n- Authenticate the customer and confirm identity verification status on file.\n\n2) Check eligibility\n- Confirm an active checking account exists and meets the 14-day tenure requirement.\n- Count existing personal savings accounts; ensure the customer is below the 5 limit.\n- Review account status; there must be no collections activity and no negative balances."
}
```

**Key Information:**
- Requires existing checking account (14+ days old)
- Max 5 savings accounts
- Tools: `open_bank_account_4821`, `transfer_funds_between_bank_accounts_7291`
- 30-day funding deadline

#### Example 3: Business Checking (Beige Enterprise)
**File:** `doc_business_checking_accounts_beige_001.json`

```json
{
  "id": "doc_business_checking_accounts_beige_001",
  "title": "Implementing Beige: Enterprise Treasury Onboarding",
  "content": "## Onboarding timeline and responsibilities\n- Confirm executive sponsorship and authorized signers before initiating onboarding.\n- Prepare onboarding documentation, treasury policy, and internal approval matrix.\n- Identify primary funding sources for initial deposits and recurring cash flows.\n\n## Funding and balance setup\n- Maintain at least $250,000 to keep your enterprise-level treasury account in good standing.\n- The monthly maintenance fee is $200.00. This fee is waived when your average balance meets or exceeds $500,000.\n- If you anticipate balance variability during early implementation, align funding schedules to preserve eligibility for the fee waiver threshold.\n\n## Dedicated support structure\n- You are assigned 2 dedicated account managers who coordinate onboarding milestones, entitlements, and operational readiness.\n- Establish a recurring operating cadence with your account team for progress tracking and rapid issue resolution.\n\n## Overdraft settings during go-live\n- Overdrafts incur a fee of $0.00.\n- If you plan to stagger incoming funds across multiple institutions, configure conservative payment windows and internal approvals to avoid negative balances.\n\n## Operational readiness checklist\n- Set signer roles and entitlements consistent with your treasury policy.\n- Add internal approval rules for payments and administrative changes in line with your governance model.\n- Validate statement delivery preferences, reporting formats, and reconciliation identifiers prior to first close.\n- Confirm that funding sources are scheduled to achieve at least $250,000 and, if desired, the waiver threshold of $500,000.\n\n## Reference values for onboarding\n| Item | Value |\n| --- | --- |\n| Monthly maintenance fee | $200.00 |\n| Minimum balance requirement | $250,000 |\n| Fee waiver balance threshold | $500,000 |\n| Dedicated account managers | 2 |\n| Overdraft fee | $0.00 |"
}
```

**Key Information:**
- Beige = Enterprise treasury account
- Minimum balance: $250,000
- Monthly fee: $200 (waived at $500k+ average balance)
- 2 dedicated account managers

#### Example 4: Credit Card Closure
**File:** `doc_credit_cards_credit_card_account_logistics_001.json`

```json
{
  "id": "doc_credit_cards_credit_card_account_logistics_001",
  "title": "How can I close a credit card account?",
  "content": "## Eligibility Requirements for Account Closure\n\nTo close your Rho-Bank credit card account, you must meet all of the following:\n\n1. Zero balance required: Your account must have an outstanding balance of $0.00 dollars. Wait for any pending transactions to post, then pay the full statement balance.\n2. No pending disputes: Accounts with active or pending transaction disputes cannot be closed (pending disputes allowed: No). Request closure only after all disputes are fully resolved.\n3. Minimum account age: Your account must have been open for at least 60 days.\n4. No pending replacement cards: If a replacement card has been ordered and not yet received or activated, complete or cancel the replacement process before requesting closure.\n\n## Rewards and Annual Fee Policies\n\n- Unredeemed rewards: You have 45 days after submitting your closure request to redeem any remaining rewards. After this period, all unredeemed rewards are permanently forfeited.\n- Annual fee refund: If you close your account within 37 days of the annual fee posting, you are eligible for a full refund of that fee. After this window, no refund is provided.\n\n## Impact on Credit Score\n\nClosing a credit card may affect your credit score by reducing your total available credit and potentially impacting your credit utilization ratio. This impact can be more significant if the card has a high credit limit or is among your oldest accounts."
}
```

**Key Information:**
- Closure requirements: $0 balance, no disputes, 60+ days old, no pending cards
- Rewards: 45-day redemption window after closure request
- Annual fee refund: within 37 days of posting

### Common Document Patterns

**Most documents contain:**

| Section | Purpose |
|---------|---------|
| Eligibility Requirements | Prerequisites for the operation |
| Step-by-Step Procedure | Ordered list of actions |
| Tool References | Internal tool names (e.g., `open_bank_account_4821`) |
| Values/Thresholds | Dollar amounts, day counts, limits |
| Warnings | Things NOT to do |

---

## embeddings.json - Cache File

**Location:** `kb/embeddings.json` (gitignored)
**Format:** JSON mapping of doc_id → base64-encoded float32 array

**Example Structure:**
```json
{
  "doc_bank_accounts_bank_accounts_(general)_001": "AAAAAAAAAAAAAAAAAAAAAA...",
  "doc_bank_accounts_bank_accounts_(general)_002": "AAAAAAAAAAAAAAAAAAAAAA...",
  "doc_business_checking_accounts_beige_001": "AAAAAAAAAAAAAAAAAAAAAAAA..."
}
```

**Generation:** Via `precompute_embeddings.py`

**Encoding Process:**
```python
# 1. Embed text
vector = _embed(["{title}\n{content}"])[0]  # 768 floats

# 2. Pack to binary
binary = struct.pack("768f", *vector)  # 3072 bytes

# 3. Base64 encode
cached = base64.b64encode(binary).decode()
```

**Usage in ingest.py:**
```python
cache = load_embedding_cache()  # {doc_id: bytes}
embedding_bytes = [cache.get(doc["id"]) for doc in documents]
```

**Purpose:**
- Instant startup (no API calls during indexing)
- No per-restart embedding costs
- Deterministic, reproducible indexing

---

## Next Part

- **Part 5**: Environment API & A2A Protocol Specifications
