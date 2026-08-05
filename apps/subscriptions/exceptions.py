class SubscriptionNotFoundError(Exception):
    pass


class SubscriptionAlreadyExistsError(Exception):
    pass


class SubscriptionGatewayNotConfiguredError(Exception):
    pass


class SubscriptionNotCancelableError(Exception):
    pass
