#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

from urllib.parse import urlencode

import freezegun
import pendulum
import pytest
from source_stripe.streams import CheckoutSessionsLineItems, CustomerBalanceTransactions, Persons, SetupAttempts


def read_from_stream(stream, sync_mode, state):
    records = []
    for slice_ in stream.stream_slices(sync_mode=sync_mode, stream_state=state):
        for record in stream.read_records(sync_mode=sync_mode, stream_slice=slice_, stream_state=state):
            records.append(record)
    return records


def test_request_headers(stream_by_name):
    stream = stream_by_name("accounts")
    headers = stream.request_headers()
    assert headers["Stripe-Version"] == "2022-11-15"


bank_accounts_full_refresh_test_case = (
    {
        "https://api.stripe.com/v1/customers?expand%5B%5D=data.sources": {
            "has_more": False,
            "object": "list",
            "url": "/v1/customers",
            "data": [
                {
                    "created": 1641038947,
                    "id": "cus_HezytZRkaQJC8W",
                    "object": "customer",
                    "total": 1,
                    "sources": {
                        "data": [
                            {
                                "id": "cs_1",
                                "object": "card",
                            },
                            {
                                "id": "cs_2",
                                "object": "bank_account",
                            },
                        ],
                        "has_more": True,
                        "object": "list",
                        "total_count": 4,
                        "url": "/v1/customers/cus_HezytZRkaQJC8W/sources",
                    },
                }
            ],
        },
        "https://api.stripe.com/v1/customers/cus_HezytZRkaQJC8W/sources?object=bank_account&starting_after=cs_2": {
            "data": [
                {
                    "id": "cs_3",
                    "object": "card",
                },
                {
                    "id": "cs_4",
                    "object": "bank_account",
                },
            ],
            "has_more": False,
            "object": "list",
            "total_count": 4,
            "url": "/v1/customers/cus_HezytZRkaQJC8W/sources",
        },
    },
    "bank_accounts",
    [
        {"id": "cs_2", "object": "bank_account", "updated": 1692802815},
        {"id": "cs_4", "object": "bank_account", "updated": 1692802815},
    ],
    "full_refresh",
    {},
)


bank_accounts_incremental_test_case = (
    {
        "https://api.stripe.com/v1/events?types%5B%5D=customer.source.created&types%5B%5D=customer.source.expiring&types"
        "%5B%5D=customer.source.updated&types%5B%5D=customer.source.deleted": {
            "data": [
                {
                    "id": "evt_1NdNFoEcXtiJtvvhBP5mxQmL",
                    "object": "event",
                    "api_version": "2020-08-27",
                    "created": 1692802016,
                    "data": {"object": {"object": "bank_account", "bank_account": "cs_1K9GK0EcXtiJtvvhSo2LvGqT", "created": 1653341716}},
                    "type": "customer.source.created",
                },
                {
                    "id": "evt_1NdNFoEcXtiJtvvhBP5mxQmL",
                    "object": "event",
                    "api_version": "2020-08-27",
                    "created": 1692802017,
                    "data": {"object": {"object": "card", "card": "cs_1K9GK0EcXtiJtvvhSo2LvGqT", "created": 1653341716}},
                    "type": "customer.source.updated",
                },
            ],
            "has_more": False,
        }
    },
    "bank_accounts",
    [{"object": "bank_account", "bank_account": "cs_1K9GK0EcXtiJtvvhSo2LvGqT", "created": 1653341716, "updated": 1692802016}],
    "incremental",
    {"updated": 1692802015},
)


@pytest.mark.parametrize(
    "requests_mock_map, stream_cls, expected_records, sync_mode, state",
    (bank_accounts_incremental_test_case, bank_accounts_full_refresh_test_case),
)
@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_lazy_substream_data_cursor_value_is_populated(
    requests_mock, stream_by_name, config, requests_mock_map, stream_cls, expected_records, sync_mode, state
):
    config["start_date"] = str(pendulum.today().subtract(days=3))
    stream = stream_by_name(stream_cls, config)
    for url, body in requests_mock_map.items():
        requests_mock.get(url, json=body)

    records = read_from_stream(stream, sync_mode, state)
    assert records == expected_records
    for record in records:
        assert bool(record[stream.cursor_field])


@pytest.mark.parametrize("requests_mock_map, stream_cls, expected_records, sync_mode, state", (bank_accounts_full_refresh_test_case,))
@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_lazy_substream_data_is_expanded(
    requests_mock, stream_by_name, config, requests_mock_map, stream_cls, expected_records, sync_mode, state
):

    config["start_date"] = str(pendulum.today().subtract(days=3))
    stream = stream_by_name("bank_accounts", config)
    for url, body in requests_mock_map.items():
        requests_mock.get(url, json=body)

    records = read_from_stream(stream, sync_mode, state)

    assert list(records) == expected_records
    assert len(requests_mock.request_history) == 2
    assert urlencode({"expand[]": "data.sources"}) in requests_mock.request_history[0].url


@pytest.mark.parametrize(
    "requests_mock_map, stream_cls, expected_records, sync_mode, state, expected_object",
    ((*bank_accounts_full_refresh_test_case, "bank_account"), (*bank_accounts_incremental_test_case, "bank_account")),
)
@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_lazy_substream_data_is_filtered(
    requests_mock, stream_by_name, config, requests_mock_map, stream_cls, expected_records, sync_mode, state, expected_object
):
    config["start_date"] = str(pendulum.today().subtract(days=3))
    stream = stream_by_name(stream_cls, config)
    for url, body in requests_mock_map.items():
        requests_mock.get(url, json=body)

    records = read_from_stream(stream, sync_mode, state)
    assert records == expected_records
    for record in records:
        assert record["object"] == expected_object


@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_created_cursor_incremental_stream(requests_mock, stream_by_name, config):
    config["start_date"] = str(pendulum.now().subtract(months=23))
    stream = stream_by_name("balance_transactions", {"lookback_window_days": 14, **config})
    requests_mock.get(
        "/v1/balance_transactions",
        [
            {
                "json": {
                    "data": [{"id": "txn_1KVQhfEcXtiJtvvhF7ox3YEm", "object": "balance_transaction", "amount": 435, "status": "available"}],
                    "has_more": False,
                }
            },
            {
                "json": {
                    "data": [
                        {"id": "txn_tiJtvvhF7ox3YEmKvVQhfEcX", "object": "balance_transaction", "amount": -9164, "status": "available"}
                    ],
                    "has_more": False,
                }
            },
        ],
    )

    slices = list(stream.stream_slices("full_refresh"))
    assert slices == [{"created[gte]": 1631199615, "created[lte]": 1662735615}, {"created[gte]": 1662735616, "created[lte]": 1692802815}]
    records = []
    for slice_ in slices:
        for record in stream.read_records("full_refresh", stream_slice=slice_):
            records.append(record)
    assert records == [
        {"id": "txn_1KVQhfEcXtiJtvvhF7ox3YEm", "object": "balance_transaction", "amount": 435, "status": "available"},
        {"id": "txn_tiJtvvhF7ox3YEmKvVQhfEcX", "object": "balance_transaction", "amount": -9164, "status": "available"},
    ]


@pytest.mark.parametrize(
    "start_date, lookback_window, max_days_from_now, stream_state, expected_start_timestamp",
    (
        ("2020-01-01T00:00:00Z", 0, 0, {}, "2020-01-01T00:00:00Z"),
        ("2020-01-01T00:00:00Z", 14, 0, {}, "2019-12-18T00:00:00Z"),
        ("2020-01-01T00:00:00Z", 0, 30, {}, "2023-07-24T15:00:15Z"),
        ("2020-01-01T00:00:00Z", 14, 30, {}, "2023-07-24T15:00:15Z"),
        ("2020-01-01T00:00:00Z", 0, 0, {"created": pendulum.parse("2022-07-17T00:00:00Z").int_timestamp}, "2022-07-17T00:00:00Z"),
        ("2020-01-01T00:00:00Z", 14, 0, {"created": pendulum.parse("2022-07-17T00:00:00Z").int_timestamp}, "2022-07-03T00:00:00Z"),
        ("2020-01-01T00:00:00Z", 0, 30, {"created": pendulum.parse("2022-07-17T00:00:00Z").int_timestamp}, "2023-07-24T15:00:15Z"),
        ("2020-01-01T00:00:00Z", 14, 30, {"created": pendulum.parse("2022-07-17T00:00:00Z").int_timestamp}, "2023-07-24T15:00:15Z"),
    ),
)
@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_get_start_timestamp(
    stream_by_name, config, start_date, lookback_window, max_days_from_now, stream_state, expected_start_timestamp
):
    config["start_date"] = start_date
    config["lookback_window_days"] = lookback_window
    stream = stream_by_name("balance_transactions", config)
    stream.start_date_max_days_from_now = max_days_from_now
    assert stream.get_start_timestamp(stream_state) == pendulum.parse(expected_start_timestamp).int_timestamp


@pytest.mark.parametrize("sync_mode", ("full_refresh", "incremental"))
def test_updated_cursor_incremental_stream_slices(stream_by_name, sync_mode):
    stream = stream_by_name("credit_notes")
    assert list(stream.stream_slices(sync_mode)) == [{}]


@pytest.mark.parametrize(
    "last_record, stream_state, expected_state",
    (({"updated": 110}, {"updated": 111}, {"updated": 111}), ({"created": 110}, {"updated": 111}, {"updated": 111})),
)
def test_updated_cursor_incremental_stream_get_updated_state(stream_by_name, last_record, stream_state, expected_state):
    stream = stream_by_name("credit_notes")
    assert stream.get_updated_state(last_record, stream_state) == expected_state


@pytest.mark.parametrize("sync_mode", ("full_refresh", "incremental"))
def test_updated_cursor_incremental_stream_read_wo_state(requests_mock, sync_mode, stream_by_name):
    requests_mock.get(
        "/v1/credit_notes",
        [
            {
                "json": {
                    "data": [
                        {
                            "id": "cn_1NGPwmEcXtiJtvvhNXwHpgJF",
                            "object": "credit_note",
                            "amount": 8400,
                            "amount_shipping": 0,
                            "created": 1686158100,
                        },
                        {
                            "id": "cn_JtvvhNXwHpgJF1NGPwmEcXti",
                            "object": "credit_note",
                            "amount": 350,
                            "amount_shipping": 150,
                            "created": 1685861100,
                        },
                    ],
                    "has_more": False,
                }
            }
        ],
    )
    stream = stream_by_name("credit_notes")
    records = [record for record in stream.read_records(sync_mode)]
    assert records == [
        {
            "id": "cn_1NGPwmEcXtiJtvvhNXwHpgJF",
            "object": "credit_note",
            "amount": 8400,
            "amount_shipping": 0,
            "updated": 1686158100,
            "created": 1686158100,
        },
        {
            "id": "cn_JtvvhNXwHpgJF1NGPwmEcXti",
            "object": "credit_note",
            "amount": 350,
            "amount_shipping": 150,
            "created": 1685861100,
            "updated": 1685861100,
        },
    ]


@freezegun.freeze_time("2023-08-23T00:00:00")
def test_updated_cursor_incremental_stream_read_w_state(requests_mock, stream_by_name):
    requests_mock.get(
        "/v1/events",
        [
            {
                "json": {
                    "data": [
                        {
                            "id": "evt_1NdNFoEcXtiJtvvhBP5mxQmL",
                            "object": "event",
                            "api_version": "2020-08-27",
                            "created": 1691629292,
                            "data": {"object": {"object": "credit_note", "invoice": "in_1K9GK0EcXtiJtvvhSo2LvGqT", "created": 1653341716}},
                            "type": "credit_note.voided",
                        }
                    ],
                    "has_more": False,
                }
            }
        ],
    )

    stream = stream_by_name("credit_notes")
    records = [
        record
        for record in stream.read_records("incremental", stream_state={"updated": pendulum.parse("2023-01-01T15:00:15Z").int_timestamp})
    ]
    assert records == [{"object": "credit_note", "invoice": "in_1K9GK0EcXtiJtvvhSo2LvGqT", "created": 1653341716, "updated": 1691629292}]


def test_checkout_session_line_items(requests_mock):

    session_id_missed = "cs_test_a165K4wNihuJlp2u3tknuohrvjAxyXFUB7nxZH3lwXRKJsadNEvIEWMUJ9"
    session_id_exists = "cs_test_a1RjRHNyGUQOFVF3OkL8V8J0lZUASyVoCtsnZYG74VrBv3qz4245BLA1BP"

    response_sessions = {
        "data": [{"id": session_id_missed, "expires_at": 100_000}, {"id": session_id_exists, "expires_at": 100_000}],
        "has_more": False,
        "object": "list",
        "url": "/v1/checkout/sessions",
    }

    response_sessions_line_items = {
        "data": [{"id": "li_1JpAUUIEn5WyEQxnfGJT5MbL"}],
        "has_more": False,
        "object": "list",
        "url": "/v1/checkout/sessions/{}/line_items".format(session_id_exists),
    }

    response_error = {
        "error": {
            "code": "resource_missing",
            "doc_url": "https://stripe.com/docs/error-codes/resource-missing",
            "message": "No such checkout session: '{}'".format(session_id_missed),
            "param": "session",
            "type": "invalid_request_error",
        }
    }

    requests_mock.get("https://api.stripe.com/v1/checkout/sessions", json=response_sessions)
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/{}/line_items".format(session_id_exists), json=response_sessions_line_items
    )
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/{}/line_items".format(session_id_missed), json=response_error, status_code=404
    )

    stream = CheckoutSessionsLineItems(start_date=100_100, account_id=None)
    records = []
    for slice_ in stream.stream_slices(sync_mode="full_refresh"):
        records.extend(stream.read_records(sync_mode="full_refresh", stream_slice=slice_))
    assert len(records) == 1


def test_customer_balance_transactions_stream_slices(requests_mock, stream_args):
    stream_args["start_date"] = pendulum.now().subtract(days=1).int_timestamp
    requests_mock.get(
        "/v1/customers",
        json={
            "data": [
                {"id": 1, "next_invoice_sequence": 1, "balance": 0, "created": 1653341716},
                {"id": 2, "created": 1653341000},
                {"id": 3, "next_invoice_sequence": 13, "balance": 343.43, "created": 1651716334},
            ]
        },
    )
    stream = CustomerBalanceTransactions(**stream_args)
    assert list(stream.stream_slices("full_refresh")) == [
        {"id": 2, "created": 1653341000, "updated": 1653341000},
        {"id": 3, "next_invoice_sequence": 13, "balance": 343.43, "created": 1651716334, "updated": 1651716334},
    ]


@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_setup_attempts(requests_mock, incremental_stream_args):
    requests_mock.get(
        "/v1/setup_intents",
        [
            {"json": {"data": [{"id": 1, "created": 111, "object": "setup_intent"}]}},
            {"json": {"data": [{"id": 2, "created": 222, "object": "setup_intent"}]}},
        ],
    )
    requests_mock.get(
        "/v1/setup_attempts",
        [
            {"json": {"data": [{"id": 1, "created": 112, "object": "setup_attempt"}]}},
            {"json": {"data": [{"id": 2, "created": 230, "object": "setup_attempt"}]}},
            {"json": {"data": [{"id": 3, "created": 345, "object": "setup_attempt"}]}},
            {"json": {"data": [{"id": 4, "created": 450, "object": "setup_attempt"}]}},
        ],
    )
    incremental_stream_args["slice_range"] = 1
    incremental_stream_args["lookback_window_days"] = 0
    incremental_stream_args["start_date"] = pendulum.now().subtract(days=2).int_timestamp
    stream = SetupAttempts(**incremental_stream_args)
    slices = list(stream.stream_slices("full_refresh"))
    assert slices == [
        {
            "created[gte]": 1692630015,
            "created[lte]": 1692716415,
            "parent": {"id": 1, "created": 111, "updated": 111, "object": "setup_intent"},
        },
        {
            "created[gte]": 1692716416,
            "created[lte]": 1692802815,
            "parent": {"id": 1, "created": 111, "updated": 111, "object": "setup_intent"},
        },
        {
            "created[gte]": 1692630015,
            "created[lte]": 1692716415,
            "parent": {"id": 2, "created": 222, "updated": 222, "object": "setup_intent"},
        },
        {
            "created[gte]": 1692716416,
            "created[lte]": 1692802815,
            "parent": {"id": 2, "created": 222, "updated": 222, "object": "setup_intent"},
        },
    ]
    records = []
    for slice_ in slices:
        for record in stream.read_records("full_refresh", stream_slice=slice_):
            records.append(record)
    assert records == [
        {"id": 1, "created": 112, "object": "setup_attempt"},
        {"id": 2, "created": 230, "object": "setup_attempt"},
        {"id": 3, "created": 345, "object": "setup_attempt"},
        {"id": 4, "created": 450, "object": "setup_attempt"},
    ]


def test_persons_wo_state(requests_mock, stream_args):
    requests_mock.get("/v1/accounts", json={"data": [{"id": 1, "object": "account", "created": 111}]})
    stream = Persons(**stream_args)
    slices = list(stream.stream_slices("full_refresh"))
    assert slices == [{"parent": {"id": 1, "object": "account", "created": 111}}]
    requests_mock.get("/v1/accounts/1/persons", json={"data": [{"id": 11, "object": "person", "created": 222}]})
    records = []
    for slice_ in slices:
        for record in stream.read_records("full_refresh", stream_slice=slice_):
            records.append(record)
    assert records == [{"id": 11, "object": "person", "created": 222, "updated": 222}]


@freezegun.freeze_time("2023-08-23T15:00:15")
def test_persons_w_state(requests_mock, stream_args):
    requests_mock.get(
        "/v1/events",
        json={
            "data": [
                {
                    "id": "evt_1NdNFoEcXtiJtvvhBP5mxQmL",
                    "object": "event",
                    "api_version": "2020-08-27",
                    "created": 1691629292,
                    "data": {"object": {"object": "person", "name": "John", "created": 1653341716}},
                    "type": "person.updated",
                }
            ],
            "has_more": False,
        },
    )
    stream = Persons(**stream_args)
    slices = list(stream.stream_slices("incremental", stream_state={"updated": pendulum.parse("2023-08-20T00:00:00").int_timestamp}))
    assert slices == [{}]
    records = [
        record
        for record in stream.read_records("incremental", stream_state={"updated": pendulum.parse("2023-08-20T00:00:00").int_timestamp})
    ]
    assert records == [{"object": "person", "name": "John", "created": 1653341716, "updated": 1691629292}]


@pytest.mark.parametrize("sync_mode, stream_state", (("full_refresh", {}), ("incremental", {}), ("incremental", {"updated": 1693987430})))
def test_cursorless_incremental_stream(requests_mock, stream_by_name, sync_mode, stream_state):
    # Testing streams that *only* have the cursor field value in incremental mode because of API discrepancies,
    # e.g. /bank_accounts does not return created/updated date, however /events?type=bank_account.updated returns the update date.
    # Key condition here is that the underlying stream has legacy cursor field set to None.
    stream = stream_by_name("external_account_bank_accounts")
    requests_mock.get(
        "/v1/accounts/<account_id>/external_accounts",
        json={
            "data": [
                {
                    "id": "ba_1Nncwa2eZvKYlo2CDILv1Q7N",
                    "object": "bank_account",
                    "account": "acct_1032D82eZvKYlo2C",
                    "bank_name": "STRIPE TEST BANK",
                    "country": "US",
                }
            ]
        },
    )
    requests_mock.get(
        "/v1/events",
        json={
            "data": [
                {
                    "id": "evt_1NdNFoEcXtiJtvvhBP5mxQmL",
                    "object": "event",
                    "api_version": "2020-08-27",
                    "created": 1691629292,
                    "data": {
                        "object": {
                            "id": "ba_1Nncwa2eZvKYlo2CDILv1Q7N",
                            "object": "bank_account",
                            "account": "acct_1032D82eZvKYlo2C",
                            "bank_name": "STRIPE TEST BANK",
                            "country": "US",
                        }
                    },
                    "type": "account.external_account.updated",
                }
            ],
            "has_more": False,
        },
    )
    for slice_ in stream.stream_slices(sync_mode=sync_mode, stream_state=stream_state):
        for record in stream.read_records(sync_mode=sync_mode, stream_state=stream_state, stream_slice=slice_):
            stream.get_updated_state(stream_state, record)
    # no assertions, this should be just a successful sync


@pytest.mark.parametrize("sync_mode, stream_state", (("full_refresh", {}), ("incremental", {}), ("incremental", {"updated": 1693987430})))
def test_cursorless_incremental_substream(requests_mock, stream_by_name, sync_mode, stream_state):
    # same for substreams
    stream = stream_by_name("bank_accounts")
    requests_mock.get(
        "/v1/customers",
        json={
            "data": [
                {"id": 1, "created": 1, "object": "customer", "sources": {"data": [{"id": 1, "object": "bank_account"}], "has_more": True}}
            ],
            "has_more": False,
        },
    )
    requests_mock.get("/v1/customers/1/sources", json={"has_more": False, "data": [{"id": 2, "object": "bank_account"}]})
    requests_mock.get(
        "/v1/events",
        json={
            "data": [
                {
                    "id": "evt_1NdNFoEcXtiJtvvhBP5mxQmL",
                    "object": "event",
                    "api_version": "2020-08-27",
                    "created": 1691629292,
                    "data": {
                        "object": {
                            "id": "ba_1Nncwa2eZvKYlo2CDILv1Q7N",
                            "object": "bank_account",
                            "account": "acct_1032D82eZvKYlo2C",
                            "bank_name": "STRIPE TEST BANK",
                            "country": "US",
                        }
                    },
                    "type": "account.external_account.updated",
                }
            ]
        },
    )
    for slice_ in stream.stream_slices(sync_mode=sync_mode, stream_state=stream_state):
        for record in stream.read_records(sync_mode=sync_mode, stream_state=stream_state, stream_slice=slice_):
            stream.get_updated_state(stream_state, record)


@pytest.mark.parametrize("stream_name", ("bank_accounts",))
def test_get_updated_state(stream_name, stream_by_name, requests_mock):
    stream = stream_by_name(stream_name)
    response = {"data": [{"id": 1, stream.cursor_field: 1695292083}]}
    requests_mock.get("/v1/credit_notes", json=response)
    requests_mock.get("/v1/balance_transactions", json=response)
    requests_mock.get("/v1/invoices", json=response)
    requests_mock.get(
        "/v1/customers",
        json={"data": [{"id": 1, "created": 1695292083, "sources": {"data": [{"id": 1, "object": "bank_account"}], "has_more": False}}]},
    )
    state = {}
    for slice_ in stream.stream_slices(sync_mode="incremental", stream_state=state):
        for record in stream.read_records(sync_mode="incremental", stream_slice=slice_, stream_state=state):
            state = stream.get_updated_state(state, record)
            assert state


@freezegun.freeze_time("2023-08-23T15:00:15Z")
def test_subscription_items_extra_request_params(requests_mock, stream_by_name, config):
    requests_mock.get(
        "/v1/subscriptions",
        json={
            "object": "list",
            "url": "/v1/subscriptions",
            "has_more": False,
            "data": [
                {
                    "id": "sub_1OApco2eZvKYlo2CEDCzwLrE",
                    "object": "subscription",
                    "created": 1699603174,
                    "items": {
                        "object": "list",
                        "data": [
                            {
                                "id": "si_OynDmET1kQPTbI",
                                "object": "subscription_item",
                                "created": 1699603175,
                                "quantity": 1,
                                "subscription": "sub_1OApco2eZvKYlo2CEDCzwLrE",
                            }
                        ],
                        "has_more": True,
                    },
                    "latest_invoice": None,
                    "livemode": False,
                }
            ],
            "has_more": False,
        },
    )
    requests_mock.get(
        "/v1/subscription_items?subscription=sub_1OApco2eZvKYlo2CEDCzwLrE",
        json={
            "object": "list",
            "url": "/v1/subscription_items",
            "has_more": False,
            "data": [
                {
                    "id": "si_OynPdzMZykmCWm",
                    "object": "subscription_item",
                    "created": 1699603884,
                    "quantity": 2,
                    "subscription": "sub_1OApco2eZvKYlo2CEDCzwLrE",
                }
            ],
        },
    )
    config["start_date"] = str(pendulum.now().subtract(days=3))
    stream = stream_by_name("subscription_items", config)
    records = read_from_stream(stream, "full_refresh", {})
    assert records == [
        {
            "id": "si_OynDmET1kQPTbI",
            "object": "subscription_item",
            "created": 1699603175,
            "quantity": 1,
            "subscription": "sub_1OApco2eZvKYlo2CEDCzwLrE",
        },
        {
            "id": "si_OynPdzMZykmCWm",
            "object": "subscription_item",
            "created": 1699603884,
            "quantity": 2,
            "subscription": "sub_1OApco2eZvKYlo2CEDCzwLrE",
        },
    ]
    assert len(requests_mock.request_history) == 2
    assert "subscription=sub_1OApco2eZvKYlo2CEDCzwLrE" in requests_mock.request_history[-1].url
