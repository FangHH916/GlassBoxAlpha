from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .config import Settings
from .models import (
    AccountState,
    Bar,
    LegAction,
    OptionContractQuote,
    OptionType,
    OrderReceipt,
    TradeProposal,
)


class Broker(Protocol):
    def get_account(self) -> AccountState: ...

    def get_bars(self, symbol: str, limit: int = 120) -> list[Bar]: ...

    def get_option_chain(self, symbol: str, spot: float) -> list[OptionContractQuote]: ...

    def submit(self, proposal: TradeProposal) -> OrderReceipt: ...

    def submit_close(self, proposal: TradeProposal, limit_credit: float) -> OrderReceipt: ...

    def get_open_positions(self) -> dict[str, float]: ...

    def health(self) -> dict[str, object]: ...


class DemoBroker:
    """Deterministic replay broker. It never connects to any external service."""

    def __init__(self, settings: Settings, seed: int = 20260828):
        self.settings = settings
        self.seed = seed
        self._orders: list[OrderReceipt] = []
        self._now = datetime.now(timezone.utc).replace(microsecond=0)
        self._cycles = 0

    def get_account(self) -> AccountState:
        return AccountState(
            equity=100_000.0,
            last_equity=100_000.0,
            buying_power=200_000.0,
            options_buying_power=100_000.0,
            option_market_value=0.0,
            daily_pnl=0.0,
            high_watermark=100_000.0,
            open_option_positions=0,
            trades_today=len(self._orders),
            options_trading_level=3,
            is_paper=True,
            market_open=True,
            minutes_to_close=180,
            account_id_masked="DEMO•••ALPHA",
            account_created_at=datetime(2026, 8, 28, 15, 1, tzinfo=timezone.utc),
            competition_account_match=True,
            competition_account_fresh=True,
            competition_balance_verified=True,
        )

    def get_bars(self, symbol: str, limit: int = 120) -> list[Bar]:
        current = datetime.now(timezone.utc).replace(microsecond=0)
        self._now = max(current, self._now + timedelta(minutes=5)) if self._cycles else current
        self._cycles += 1
        rng = random.Random(self.seed + sum(ord(char) for char in symbol))
        base = 640.0 if symbol == "SPY" else 580.0
        closes: list[float] = []
        price = base
        for index in range(limit):
            # Gentle positive regime with deterministic micro-noise.
            drift = 0.00065 + 0.00012 * math.sin(index / 7)
            shock = rng.gauss(0, 0.00035)
            price *= 1 + drift + shock
            closes.append(price)
        start = self._now - timedelta(minutes=5 * limit)
        bars: list[Bar] = []
        previous = closes[0]
        for index, close in enumerate(closes):
            wiggle = max(0.04, close * 0.0007)
            bars.append(
                Bar(
                    timestamp=start + timedelta(minutes=5 * (index + 1)),
                    open=round(previous, 4),
                    high=round(max(previous, close) + wiggle, 4),
                    low=round(min(previous, close) - wiggle, 4),
                    close=round(close, 4),
                    volume=1_000_000 + index * 2_500,
                )
            )
            previous = close
        return bars

    def get_option_chain(self, symbol: str, spot: float) -> list[OptionContractQuote]:
        expiry = _next_weekday(self._now.date() + timedelta(days=12), 4)
        result: list[OptionContractQuote] = []
        center = round(spot)
        for option_type in (OptionType.CALL, OptionType.PUT):
            for strike in range(center - 12, center + 13):
                theoretical, delta = _black_scholes(
                    spot=spot,
                    strike=float(strike),
                    dte=(expiry - self._now.date()).days,
                    volatility=0.21,
                    option_type=option_type,
                )
                midpoint = max(0.08, theoretical)
                half_spread = max(0.01, midpoint * 0.025)
                bid = round(max(0.01, midpoint - half_spread), 2)
                ask = round(max(bid + 0.01, midpoint + half_spread), 2)
                result.append(
                    OptionContractQuote(
                        symbol=_occ_symbol(symbol, expiry, option_type, float(strike)),
                        underlying=symbol,
                        option_type=option_type,
                        strike=float(strike),
                        expiration=expiry,
                        bid=bid,
                        ask=ask,
                        bid_size=40,
                        ask_size=45,
                        delta=round(delta, 4),
                        gamma=0.03,
                        theta=-0.11,
                        implied_volatility=0.21,
                        open_interest=1_200 + abs(strike - center) * 30,
                        tradable=True,
                        quote_timestamp=self._now,
                        feed="replay",
                    )
                )
        return result

    def submit(self, proposal: TradeProposal) -> OrderReceipt:
        receipt = OrderReceipt(
            order_id=f"demo-{len(self._orders) + 1:04d}",
            client_order_id=proposal.proposal_id,
            status="simulated_fill",
            submitted_at=self._now,
            paper=True,
        )
        self._orders.append(receipt)
        return receipt

    def submit_close(self, proposal: TradeProposal, limit_credit: float) -> OrderReceipt:
        receipt = OrderReceipt(
            order_id=f"demo-close-{len(self._orders) + 1:04d}",
            client_order_id=f"{proposal.proposal_id[:31]}-x",
            status="simulated_close",
            submitted_at=self._now,
            paper=True,
        )
        self._orders.append(receipt)
        return receipt

    def get_open_positions(self) -> dict[str, float]:
        return {}

    def health(self) -> dict[str, object]:
        return {
            "broker": "deterministic replay",
            "connected": True,
            "paper_only": True,
            "data_feed": "synthetic replay",
            "execution_backend": "none",
        }


class AlpacaBroker:
    """Read from Alpaca's Trading/Data APIs and execute on paper only."""

    def __init__(self, settings: Settings):
        if not settings.alpaca_api_key or not settings.alpaca_api_secret:
            raise ValueError("Alpaca API credentials are required")
        try:
            from alpaca.data.historical.option import OptionHistoricalDataClient
            from alpaca.data.historical.stock import StockHistoricalDataClient
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise RuntimeError("Install alpaca-py before using BROKER_MODE=alpaca") from exc
        self.settings = settings
        self.trading = TradingClient(settings.alpaca_api_key, settings.alpaca_api_secret, paper=True)
        self.stocks = StockHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_api_secret)
        self.options = OptionHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_api_secret)
        self._last_account_id: str | None = None
        self._last_account_number: str | None = None

    def get_account(self) -> AccountState:
        from alpaca.trading.enums import AssetClass

        account = self.trading.get_account()
        clock = self.trading.get_clock()
        positions = self.trading.get_all_positions()
        account_id = str(account.id)
        account_number = str(account.account_number)
        self._last_account_id = account_id
        self._last_account_number = account_number
        created_at = _aware(account.created_at)
        competition_start = datetime.fromisoformat(self.settings.competition_start_utc.replace("Z", "+00:00"))
        option_positions = [item for item in positions if item.asset_class == AssetClass.US_OPTION]
        option_market_value = sum(abs(float(item.market_value or 0)) for item in option_positions)
        timestamp = _aware(clock.timestamp)
        next_close = _aware(clock.next_close)
        minutes_to_close = max(0, int((next_close - timestamp).total_seconds() // 60)) if clock.is_open else None
        equity = float(account.equity)
        last_equity = float(account.last_equity)
        return AccountState(
            equity=equity,
            last_equity=last_equity,
            buying_power=float(account.buying_power),
            options_buying_power=float(account.options_buying_power or 0),
            option_market_value=option_market_value,
            daily_pnl=equity - last_equity,
            high_watermark=max(equity, last_equity),
            open_option_positions=len(option_positions),
            trades_today=0,
            options_trading_level=int(account.options_trading_level or 0),
            is_paper=True,
            market_open=bool(clock.is_open),
            minutes_to_close=minutes_to_close,
            account_id_masked=_mask(account_id),
            account_created_at=created_at,
            competition_account_match=(
                bool(self.settings.competition_account_id)
                and self.settings.competition_account_id in {account_id, account_number}
            ),
            competition_account_fresh=created_at >= competition_start,
            competition_balance_verified=False,
        )

    def get_bars(self, symbol: str, limit: int = 120) -> list[Bar]:
        from alpaca.common.enums import Sort
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        now = datetime.now(timezone.utc)
        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            start=now - timedelta(days=10),
            end=now,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            limit=max(limit + 1, 80),
            sort=Sort.DESC,
            feed=DataFeed.IEX,
        )
        response = self.stocks.get_stock_bars(request)
        raw = sorted(response[symbol], key=lambda item: _aware(item.timestamp))
        # Do not use an incomplete five-minute bar.
        completed = [item for item in raw if (now - _aware(item.timestamp)).total_seconds() >= 300]
        return [
            Bar(
                timestamp=_aware(item.timestamp),
                open=float(item.open),
                high=float(item.high),
                low=float(item.low),
                close=float(item.close),
                volume=float(item.volume),
            )
            for item in completed[-limit:]
        ]

    def get_option_chain(self, symbol: str, spot: float) -> list[OptionContractQuote]:
        from alpaca.data.enums import OptionsFeed
        from alpaca.data.requests import OptionChainRequest
        from alpaca.trading.requests import GetOptionContractsRequest

        today = datetime.now(timezone.utc).date()
        lower_expiry = today + timedelta(days=self.settings.min_dte)
        upper_expiry = today + timedelta(days=self.settings.max_dte)
        lower_strike = round(spot * 0.94, 2)
        upper_strike = round(spot * 1.06, 2)
        contracts_response = self.trading.get_option_contracts(
            GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date_gte=lower_expiry,
                expiration_date_lte=upper_expiry,
                strike_price_gte=str(lower_strike),
                strike_price_lte=str(upper_strike),
                limit=10_000,
            )
        )
        metadata = {item.symbol: item for item in contracts_response.option_contracts}
        feed = OptionsFeed.OPRA if self.settings.option_feed == "opra" else OptionsFeed.INDICATIVE
        snapshots = self.options.get_option_chain(
            OptionChainRequest(
                underlying_symbol=symbol,
                feed=feed,
                strike_price_gte=lower_strike,
                strike_price_lte=upper_strike,
                expiration_date_gte=lower_expiry,
                expiration_date_lte=upper_expiry,
            )
        )
        result: list[OptionContractQuote] = []
        for option_symbol, snapshot in snapshots.items():
            contract = metadata.get(option_symbol)
            quote = snapshot.latest_quote
            if contract is None or quote is None:
                continue
            greeks = snapshot.greeks
            contract_type = getattr(contract.type, "value", str(contract.type)).lower()
            result.append(
                OptionContractQuote(
                    symbol=option_symbol,
                    underlying=symbol,
                    option_type=OptionType.CALL if contract_type == "call" else OptionType.PUT,
                    strike=float(contract.strike_price),
                    expiration=_date(contract.expiration_date),
                    bid=float(quote.bid_price or 0),
                    ask=float(quote.ask_price or 0),
                    bid_size=int(quote.bid_size or 0),
                    ask_size=int(quote.ask_size or 0),
                    delta=float(greeks.delta) if greeks and greeks.delta is not None else None,
                    gamma=float(greeks.gamma) if greeks and greeks.gamma is not None else None,
                    theta=float(greeks.theta) if greeks and greeks.theta is not None else None,
                    implied_volatility=float(snapshot.implied_volatility) if snapshot.implied_volatility is not None else None,
                    open_interest=int(float(contract.open_interest or 0)),
                    tradable=bool(contract.tradable),
                    quote_timestamp=_aware(quote.timestamp or datetime.now(timezone.utc) - timedelta(days=1)),
                    feed=self.settings.option_feed,
                )
            )
        return result

    def submit(self, proposal: TradeProposal) -> OrderReceipt:
        if not self.settings.paper_execution_unlocked:
            raise PermissionError("Paper execution is locked; preview mode remains available")
        if self.settings.alpaca_execution_backend == "cli":
            return self._submit_cli(proposal)
        return self._submit_sdk(proposal)

    def submit_close(self, proposal: TradeProposal, limit_credit: float) -> OrderReceipt:
        if not self.settings.paper_execution_unlocked:
            raise PermissionError("Paper execution is locked; an exit was not submitted")
        if limit_credit <= 0:
            raise ValueError("Exit limit credit must be positive")
        if self.settings.alpaca_execution_backend == "cli":
            return self._submit_cli_payload(_close_order_payload(proposal, limit_credit), proposal, closing=True)
        return self._submit_close_sdk(proposal, limit_credit)

    def get_open_positions(self) -> dict[str, float]:
        from alpaca.trading.enums import AssetClass

        return {
            str(item.symbol): float(item.qty)
            for item in self.trading.get_all_positions()
            if item.asset_class == AssetClass.US_OPTION
        }

    def _submit_cli(self, proposal: TradeProposal) -> OrderReceipt:
        return self._submit_cli_payload(_order_payload(proposal), proposal, closing=False)

    def _submit_cli_payload(
        self,
        payload: dict[str, object],
        proposal: TradeProposal,
        *,
        closing: bool,
    ) -> OrderReceipt:
        if shutil.which(self.settings.alpaca_cli_path) is None:
            raise RuntimeError("Official Alpaca CLI was not found on PATH")
        environment = os.environ.copy()
        environment["ALPACA_API_KEY"] = self.settings.alpaca_api_key or ""
        environment["ALPACA_SECRET_KEY"] = self.settings.alpaca_api_secret or ""
        environment["ALPACA_QUIET"] = "1"
        environment.pop("ALPACA_LIVE_TRADE", None)
        process = subprocess.run(
            [self.settings.alpaca_cli_path, "api", "POST", "/v2/orders"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=environment,
        )
        if process.returncode != 0:
            error = process.stderr.strip()[:500]
            raise RuntimeError(f"Alpaca CLI rejected the paper order (exit {process.returncode}): {error}")
        body = json.loads(process.stdout)
        return OrderReceipt(
            order_id=str(body.get("id", "unknown")),
            client_order_id=str(body.get("client_order_id", f"{proposal.proposal_id}-x" if closing else proposal.proposal_id)),
            status=str(body.get("status", "accepted")),
            submitted_at=_parse_datetime(body.get("submitted_at")),
            paper=True,
        )

    def _submit_close_sdk(self, proposal: TradeProposal, limit_credit: float) -> OrderReceipt:
        from alpaca.trading.enums import OrderClass, OrderSide, OrderType, PositionIntent, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

        client_id = f"{proposal.proposal_id[:31]}-x"
        if len(proposal.legs) == 1:
            request = LimitOrderRequest(
                symbol=proposal.legs[0].contract.symbol,
                qty=proposal.quantity,
                side=OrderSide.SELL,
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_credit,
                client_order_id=client_id,
                position_intent=PositionIntent.SELL_TO_CLOSE,
            )
        else:
            close_legs = [
                OptionLegRequest(
                    symbol=leg.contract.symbol,
                    ratio_qty=leg.ratio,
                    side=OrderSide.SELL if leg.action is LegAction.BUY_TO_OPEN else OrderSide.BUY,
                    position_intent=(
                        PositionIntent.SELL_TO_CLOSE
                        if leg.action is LegAction.BUY_TO_OPEN
                        else PositionIntent.BUY_TO_CLOSE
                    ),
                )
                for leg in proposal.legs
            ]
            request = LimitOrderRequest(
                qty=proposal.quantity,
                type=OrderType.LIMIT,
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                limit_price=-round(limit_credit, 2),
                client_order_id=client_id,
                legs=close_legs,
            )
        order = self.trading.submit_order(order_data=request)
        return OrderReceipt(
            order_id=str(order.id),
            client_order_id=str(order.client_order_id),
            status=getattr(order.status, "value", str(order.status)),
            submitted_at=_aware(order.submitted_at or datetime.now(timezone.utc)),
            paper=True,
        )

    def _submit_sdk(self, proposal: TradeProposal) -> OrderReceipt:
        from alpaca.trading.enums import OrderClass, OrderSide, OrderType, PositionIntent, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

        if len(proposal.legs) == 1:
            leg = proposal.legs[0]
            request = LimitOrderRequest(
                symbol=leg.contract.symbol,
                qty=proposal.quantity,
                side=OrderSide.BUY,
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                limit_price=proposal.limit_debit,
                client_order_id=proposal.proposal_id,
                position_intent=PositionIntent.BUY_TO_OPEN,
            )
        else:
            legs = [
                OptionLegRequest(
                    symbol=leg.contract.symbol,
                    ratio_qty=leg.ratio,
                    side=OrderSide.BUY if leg.action is LegAction.BUY_TO_OPEN else OrderSide.SELL,
                    position_intent=(
                        PositionIntent.BUY_TO_OPEN
                        if leg.action is LegAction.BUY_TO_OPEN
                        else PositionIntent.SELL_TO_OPEN
                    ),
                )
                for leg in proposal.legs
            ]
            request = LimitOrderRequest(
                qty=proposal.quantity,
                type=OrderType.LIMIT,
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                limit_price=proposal.limit_debit,
                client_order_id=proposal.proposal_id,
                legs=legs,
            )
        order = self.trading.submit_order(order_data=request)
        return OrderReceipt(
            order_id=str(order.id),
            client_order_id=str(order.client_order_id),
            status=getattr(order.status, "value", str(order.status)),
            submitted_at=_aware(order.submitted_at or datetime.now(timezone.utc)),
            paper=True,
        )

    def health(self) -> dict[str, object]:
        cli_available = shutil.which(self.settings.alpaca_cli_path) is not None
        return {
            "broker": "Alpaca paper",
            "connected": True,
            "paper_only": True,
            "data_feed": self.settings.option_feed,
            "execution_backend": self.settings.alpaca_execution_backend,
            "cli_available": cli_available,
        }

    @property
    def full_account_id(self) -> str | None:
        return self._last_account_id

    @property
    def full_account_number(self) -> str | None:
        return self._last_account_number


def build_broker(settings: Settings) -> Broker:
    return DemoBroker(settings) if settings.mode == "demo" else AlpacaBroker(settings)


def _order_payload(proposal: TradeProposal) -> dict[str, object]:
    if len(proposal.legs) == 1:
        leg = proposal.legs[0]
        return {
            "symbol": leg.contract.symbol,
            "qty": str(proposal.quantity),
            "side": "buy",
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(proposal.limit_debit),
            "position_intent": "buy_to_open",
            "client_order_id": proposal.proposal_id,
        }
    return {
        "qty": str(proposal.quantity),
        "type": "limit",
        "time_in_force": "day",
        "order_class": "mleg",
        "limit_price": str(proposal.limit_debit),
        "client_order_id": proposal.proposal_id,
        "legs": [
            {
                "symbol": leg.contract.symbol,
                "ratio_qty": str(leg.ratio),
                "side": "buy" if leg.action is LegAction.BUY_TO_OPEN else "sell",
                "position_intent": leg.action.value,
            }
            for leg in proposal.legs
        ],
    }


def _close_order_payload(proposal: TradeProposal, limit_credit: float) -> dict[str, object]:
    client_id = f"{proposal.proposal_id[:31]}-x"
    if len(proposal.legs) == 1:
        return {
            "symbol": proposal.legs[0].contract.symbol,
            "qty": str(proposal.quantity),
            "side": "sell",
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(round(limit_credit, 2)),
            "position_intent": "sell_to_close",
            "client_order_id": client_id,
        }
    return {
        "qty": str(proposal.quantity),
        "type": "limit",
        "time_in_force": "day",
        "order_class": "mleg",
        # Alpaca represents a net credit as a negative MLeg limit price.
        "limit_price": str(-round(limit_credit, 2)),
        "client_order_id": client_id,
        "legs": [
            {
                "symbol": leg.contract.symbol,
                "ratio_qty": str(leg.ratio),
                "side": "sell" if leg.action is LegAction.BUY_TO_OPEN else "buy",
                "position_intent": "sell_to_close" if leg.action is LegAction.BUY_TO_OPEN else "buy_to_close",
            }
            for leg in proposal.legs
        ],
    }


def _black_scholes(
    *, spot: float, strike: float, dte: int, volatility: float, option_type: OptionType
) -> tuple[float, float]:
    time = max(dte / 365, 1 / 365)
    rate = 0.04
    sigma_sqrt = volatility * math.sqrt(time)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * time) / sigma_sqrt
    d2 = d1 - sigma_sqrt
    normal = lambda value: 0.5 * (1 + math.erf(value / math.sqrt(2)))
    discount = math.exp(-rate * time)
    if option_type is OptionType.CALL:
        price = spot * normal(d1) - strike * discount * normal(d2)
        delta = normal(d1)
    else:
        price = strike * discount * normal(-d2) - spot * normal(-d1)
        delta = normal(d1) - 1
    return max(0.01, price), delta


def _next_weekday(value: date, weekday: int) -> date:
    return value + timedelta(days=(weekday - value.weekday()) % 7)


def _occ_symbol(underlying: str, expiry: date, option_type: OptionType, strike: float) -> str:
    side = "C" if option_type is OptionType.CALL else "P"
    return f"{underlying}{expiry:%y%m%d}{side}{int(round(strike * 1000)):08d}"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _parse_datetime(value: object) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _mask(value: str) -> str:
    return value if len(value) <= 8 else f"{value[:4]}•••{value[-4:]}"
