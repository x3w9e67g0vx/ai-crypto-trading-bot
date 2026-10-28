---
id: 10
title: How your AI rivals think
question: On test data a model guessed the direction right 54% of the time. What does that mean?
options: It will always make money | A small edge that fees and mistakes can easily eat | The model is broken
answer: 1
---
## What the models do

The three AI personas — LSTM, Random Forest and logistic regression — look at recent 5-minute candles and indicators and output a **probability of the price going up**. It is not knowledge of the future, just an estimate based on similar situations in the past.

## Character

The personas use the same probabilities differently:

- the aggressive one enters at 55% and takes a large position;
- the cautious one waits for 65% and risks little;
- the rookie ignores the trend.

## Why AI gets it wrong

- **Markets change**: a model learns from the past, and the future does not always look like it.
- **Overfitting**: a model can "memorize" history instead of finding a pattern.
- **Honest testing**: a model's result only means something on data it never saw during training (out-of-sample).

## How to use it

An AI opinion is one more indicator, not an order. Compare: if the trend, RSI and the AIs all say the same, you can be more confident. Beating the AI is a real goal: it trades by the same rules as you.
