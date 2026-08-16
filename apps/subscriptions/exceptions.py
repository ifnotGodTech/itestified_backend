class SubscriptionNotFoundError(Exception):
    pass


class SubscriptionAlreadyExistsError(Exception):
    pass


class SubscriptionGatewayNotConfiguredError(Exception):
    pass


class SubscriptionNotCancelableError(Exception):
    pass


class SubscriptionUnsupportedCurrencyError(Exception):
    pass


class PremiumPricingInvalidCurrencyError(Exception):
    pass


class PremiumPricingInvalidAmountError(Exception):
    pass
