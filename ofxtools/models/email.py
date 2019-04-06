# coding: utf-8
"""
email - OFX Section 9
"""
# stdlib imports
from copy import deepcopy

# local imports
from ofxtools.Types import String, Decimal, Integer, OneOf, DateTime, Bool
from ofxtools.models.base import Aggregate, SubAggregate, Unsupported, List
from ofxtools.models.wrapperbases import TrnRq, TrnRs, TranList, SyncRqList, SyncRsList
from ofxtools.models.profile import MSGSETCORE


__all__ = [
    "MAIL",
    "MAILRQ",
    "MAILRS",
    "MAILTRNRQ",
    "MAILTRNRS",
    "MAILSYNCRQ",
    "MAILSYNCRS",
    "GETMIMERQ",
    "GETMIMERS",
    "GETMIMETRNRQ",
    "GETMIMETRNRS",
    "EMAILMSGSRQV1",
    "EMAILMSGSRSV1",
    "EMAILMSGSETV1",
    "EMAILMSGSET",
]


class MAIL(Aggregate):
    """ OFX section 9.2.2 """

    userid = String(32, required=True)
    dtcreated = DateTime(required=True)
    frm = String(32, required=True)
    to = String(32, required=True)
    subject = String(60, required=True)
    msgbody = String(10000, required=True)
    incimages = Bool(required=True)
    usehtml = Bool(required=True)

    @staticmethod
    def groom(elem):
        """
        Rename all Elements tagged FROM (reserved Python keyword) to FROM
        """
        # Keep input free of side effects
        elem = deepcopy(elem)

        frm = elem.find("./FROM")
        if frm is not None:
            frm.tag = "FRM"

        return super(MAIL, MAIL).groom(elem)

    @staticmethod
    def ungroom(elem):
        """
        Rename FRM back to FROM
        """
        # Keep input free of side effects
        elem = deepcopy(elem)

        frm = elem.find("./FRM")
        if frm is not None:
            frm.tag = "FROM"

        return super(MAIL, MAIL).ungroom(elem)


class MAILRQ(Aggregate):
    """ OFX section 9.2.3 """

    mail = SubAggregate(MAIL, required=True)


class MAILRS(Aggregate):
    """ OFX section 9.2.3 """

    mail = SubAggregate(MAIL, required=True)


class MAILTRNRQ(TrnRq):
    """ OFX section 9.2.3 """

    mailrq = SubAggregate(MAILRQ, required=True)


class MAILTRNRS(TrnRs):
    """ OFX section 9.2.3 """

    mailrs = SubAggregate(MAILRS)


class MAILSYNCRQ(SyncRqList):
    """ OFX section 9.2.4 """

    incimages = Bool(required=True)
    usehtml = Bool(required=True)

    dataTags = ["MAILTRNRQ"]


class MAILSYNCRS(SyncRsList):
    """ OFX section 9.2.4 """

    dataTags = ["MAILTRNRS"]


class GETMIMERQ(Aggregate):
    """ OFX section 9.3.1 """

    url = String(255, required=True)


class GETMIMERS(Aggregate):
    """ OFX section 9.3.1 """

    url = String(255, required=True)


class GETMIMETRNRQ(TrnRq):
    """ OFX section 9.3.2 """

    getmimerq = SubAggregate(GETMIMERQ, required=True)


class GETMIMETRNRS(TrnRs):
    """ OFX section 9.3.2 """

    getmimers = SubAggregate(GETMIMERS)


class EMAILMSGSRQV1(List):
    """ OFX section 9.4.1.1 """

    dataTags = ["MAILTRNRQ", "GETMIMETRNRQ", "MAILSYNCRQ"]


class EMAILMSGSRSV1(List):
    """ OFX section 9.4.1.2 """

    dataTags = ["MAILTRNRS", "GETMIMETRNRS", "MAILSYNCRS"]


class EMAILMSGSETV1(Aggregate):
    """ OFX section 9.4.2 """

    msgsetcore = SubAggregate(MSGSETCORE, required=True)
    mailsup = Bool(required=True)
    getmimesup = Bool(required=True)


class EMAILMSGSET(Aggregate):
    """ OFX section 9.4.2 """

    emailmsgsetv1 = SubAggregate(EMAILMSGSETV1, required=True)
