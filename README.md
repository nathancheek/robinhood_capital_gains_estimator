# Robinhood Capital Gains Estimator

Parse Robinhood transaction CSVs to estimate capital gains for the current year

## Usage

1. Download Robinhood "account activity report" transaction CSVs covering the history of your account. You may need to make multiple requests, for example one per year.
2. Run `robinhood_capital_gains_estimator.py transactions.csv` to calculate long and short term capital gains for the current year. You can pass in multiple files, or a directory of CSVs. Pass multiple files in chronological order, or if passing in a directory, name the enclosed CSVs such that when sorted by name, they will be in chronological order.

## Notes

This script calculates an estimate for capital gains given the provided data, but it may not match the final values calculated by Robinhood. For example, Robinhood does not always provide cost basis data for older transactions in their account activity reports. In such cases, the script simply assumes a cost basis of `0`. Some other transaction types such as `SXCH` and `MRGS` are also processed with cost basis assumed to be `0`. There may also be some transaction types that this script is not aware of. For example, this script has not been tested with stock options transactions. In addition, this script assumes FIFO transaction ordering.

## How it Works

### Data structures

* `Lot` class:
    * `prev_lot` (Reference to previous `Lot`)
    * `instrument` (Instrument name i.e. AAPL or SPY)
    * `purchase_date` (Date when shares purchased)
    * `purchase_price` (Price per share when purchased)
    * `quantity` (Quantity of shares)
    * `sell_date` (Date when shares sold)
    * `sell_price` (Price per share when sold)
    * `next_lot` (Reference to next `Lot`)
* `lot_roots` (dict with references to the oldest `Lot` for each instrument)
* `lot_heads` (dict with references to the newest `Lot` for each instrument)
* `current_quantities` (dict containing the current `quantity` of each instrument)

### Algorithm

* Iterate through transactions (`Buy`, `CONV`, `SXCH`, `MRGS`, `Sell`, and `SPL`) to build up a chain of lots for each instrument
    * If the transaction is a `Buy`, `CONV`, `SXCH`, or `MRGS` transaction, a new `Lot` is created and appended to the end of that instrument's chain. The `purchase_price` is set to 0 for `CONV`, `SXCH`, and `MRGS` transactions (inaccurate but easier to handle).
    * If a `Sell` transaction, the `Lot` chain is traversed from its `ROOT`, marking lots as sold until the amount in the `Sell` transaction is fully allotted. If this causes a `Lot` to be only partially sold, that `Lot` is split into two lots, with the first `Lot` completely sold and the second `Lot` completely unsold.
    * If a `SPL` transaction, the `Lot` chain is traversed from its `HEAD` until a sold lot is found, multiplying `quantity` of each unsold `Lot` by the `split_ratio`. `current_quantities` is also updated to store the new quantity of that instrument.
* To calculate capital gains for current year, start at the `HEAD` of each instrument, iterate backwards until a sold lot is hit, then start counting profits per lot until hitting a lot sold prior to the current year.

## Improvements

Reverse splits (`SPR`) are not yet supported.

Currently, dividends (`CDIV`) and stock lending income (`SLIP`) are ignored. These could be tracked and included in the output.

Robinhood seems to have a bug where their stock split (`SPL` and `SPR`) transactions are logged to 4 decimal places, even though shares are held to 6 decimal places. This can cause stock split calculation errors. This script currently checks for such situations and prompts the user to input the correct split ratio. I have submitted a bug report to Robinhood, so hopefully this will get resolved in due time.