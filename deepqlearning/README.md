# Deep Reinforcement Learning for Financial Planning

Train an AI agent to make financial decisions over a person's lifetime. The agent learns to manage bank accounts, retirement funds, debt, and lifestyle choices to maximize long-term financial well-being.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r ../requirements.txt requirements-rl.txt
```

### 2. Train Your First Agent
```bash
# Basic training scenario (recommended for beginners)
python train_financial_agent.py --scenario basic --episodes 1000

# High earner scenario
python train_financial_agent.py --scenario high_earner --episodes 1500
```

### 3. Interactive Tutorial
For a step-by-step walkthrough, open the Jupyter notebook:
```bash
jupyter notebook Training_Example.ipynb
```

## 🎯 Training Scenarios

Choose from pre-configured financial scenarios:

- **`basic`** - Standard middle-class income profile (great for learning)
- **`high_earner`** - High income with complex investment decisions
- **`low_earner`** - Limited income requiring careful budgeting
- **`mid_career`** - Starting training from age 35-40

## 🛠️ Training Options

### Basic Training
```bash
# Train with default settings
python train_financial_agent.py --scenario basic

# Train for specific number of episodes
python train_financial_agent.py --scenario high_earner --episodes 2000
```

### Continue Training from Saved Model
```bash
# Load and continue training an existing model
python train_financial_agent.py --scenario basic --load_model models/financial_dqn_basic.pt --episodes 500
```

### Evaluation Only
```bash
# Evaluate a trained model without additional training
python train_financial_agent.py --scenario basic --eval_only --load_model models/financial_dqn_basic.pt
```

> **Checkpoint compatibility:** checkpoints are versioned with a `MODEL_VERSION` constant and
> saved as tensor-only `.pt` files plus a `.history.json` sidecar, so they load under modern
> PyTorch defaults (`torch.load(..., weights_only=True)`) without any environment-variable
> workarounds. Checkpoints produced before the reward/action-space redesign carry an older
> version and are not comparable; loading one prints a warning.

### Generate Training Plots
```bash
# Display training progress plots
python train_financial_agent.py --scenario basic --plot_results

# Save plots to file
python train_financial_agent.py --scenario basic --plot_results --save_plots plots/basic_training.png
```

## 🎮 How It Works

1. **State Observation** - Agent sees financial situation (account balances, debt, income, age, etc.)
2. **Action Selection** - Chooses from 16 implemented financial actions (see below)
3. **Reward Feedback** - Gets rewarded for growing net worth, penalized for poor decisions and bankruptcy
4. **Learning** - Updates its strategy based on experience

### Actions

Every action below is fully implemented and reachable — the environment creates the accounts each
acts on, and legality is decided solely by each action's `can_execute` (a property test enforces
that any legal action executes successfully):

- **Contributions/transfers** from the bank account into the 401k (pre-tax / Roth), Traditional
  IRA, Roth IRA, brokerage, and HSA (capped accounts respect their annual contribution limits).
- **Withdrawals** back to the bank from the 401k (pre-tax / Roth), Traditional IRA, Roth IRA,
  brokerage, and HSA (a 10% early-withdrawal penalty applies to tax-advantaged accounts before
  age 59.5).
- **Lifestyle**: increase spending, decrease spending, retire early.
- **No action**.

## 🔧 Customizing Training

### Modify Scenarios
Edit the scenario configurations in `train_financial_agent.py` to adjust:
- Starting financial conditions
- Income profiles
- Training duration
- Model architecture

### Adjust Reward Function
Modify the reward calculation in `environment.py` to emphasize different objectives:
- Wealth accumulation vs. spending satisfaction
- Early retirement vs. financial security
- Risk tolerance levels

### Add New Actions
Extend the action space in `actions.py` to include new account types or life decisions. Add the
`ActionType`, implement its `can_execute`/`execute`, and make sure the environment creates any
account it needs so the action is actually reachable (the property test will flag actions that
are declared legal but fail to execute).
