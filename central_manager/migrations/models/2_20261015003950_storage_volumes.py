from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "storage_volumes" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "path" VARCHAR(400) NOT NULL,
    "position" INT NOT NULL,
    "quota_bytes" BIGINT,
    "accepting" BOOL NOT NULL,
    "is_default" BOOL NOT NULL,
    "state" VARCHAR(16) NOT NULL,
    "state_detail" VARCHAR(256),
    "total_bytes" BIGINT,
    "free_bytes" BIGINT,
    "recordings_bytes" BIGINT,
    "writing" BOOL NOT NULL,
    "last_report_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "node_id" INT NOT NULL REFERENCES "media_nodes" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_storage_vol_node_id_bc5140" UNIQUE ("node_id", "path")
);
COMMENT ON COLUMN "storage_volumes"."state" IS 'PENDING: PENDING\nOK: OK\nFULL: FULL\nUNAVAILABLE: UNAVAILABLE\nERROR: ERROR';
COMMENT ON TABLE "storage_volumes" IS 'A place where a media node may store recordings: a folder on a local drive or a network share.';
        ALTER TABLE "recording_segments" ADD "volume_id" INT;
        ALTER TABLE "recording_segments" ADD CONSTRAINT "fk_recordin_storage__87205122" FOREIGN KEY ("volume_id") REFERENCES "storage_volumes" ("id") ON DELETE SET NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "recording_segments" DROP CONSTRAINT IF EXISTS "fk_recordin_storage__87205122";
        ALTER TABLE "recording_segments" DROP COLUMN "volume_id";
        DROP TABLE IF EXISTS "storage_volumes";"""


MODELS_STATE = (
    "eJztXW1z2joW/isaPiWz2WxCXm92Z2cIkJYbAh0gbfeWO65iC/DEyK5tQtm7/e97JGP8Dr"
    "YLxqbuh9RIOrL8SJaOnnOO/FdlqkpEMU7reEp0XLlDf1UoXMKFL+cEVbCmOekswcQvCi8q"
    "8jI8Db8Ypo5FE5JHWDEIJEnEEHVZM2WVQiqdKQpLVEUoKNOxkzSj8rcZEUx1TMwJ0SHjy5"
    "+QLFOJfCeG/VN7FUYyUSRPW2WJ3ZunC+ZC42ktaj7wguxuL4KoKrMpdQprC3Oi0lVpmZos"
    "dUwoPIlJWPWmPmPNZ61bPqj9RFZLnSJWE10yEhnhmWK6HvdFcNIqgtDpDoR+cyAIlQQAiS"
    "pl4EJTDf70Y9aEv1fPL28uby+uL2+hCG/mKuXmh3VrBxhLkMPTGVR+8HxsYqsEx9gBlf8f"
    "gLU+wXo4rnZ5H7LQZD+yNo7roLUTHGyd8ZQFuFP8XVAIHZsT+HlevV0D5cdar/6+1juCUs"
    "fsliq8ANaL0VlmVa08hreDr7tlAZgH5HvE8PWJpUJ7OUzzAvYabAfNzwNW89QwviluSI+e"
    "ap852tPFMqfd7byzi7u6oN7u3vuQnxlETzq63TKHgHkGA1zDhjFX9ZC5ORpmt8zhwVy9uo"
    "4BM5SKhJnneWEmlD16CMr3qqoQTMOBdkn5cH4BsV3N2Pb6mO0kct/ttj2TyH3LP0s8P903"
    "YYBz3KGQbBL3IumArROTUNY0QcILI4HWERTcrIFsC/WbXGsgDriiTtiTC9gMAtuAHFOekn"
    "B0vZI+ZKWl6Kl9UUR9BB5Q6lJlsXyJ1i2Zradmf1B7+uAZ8o3aoMlyqp4100498s84q0rQ"
    "p9bgPWI/0R/dTpPDqxrmWOd3dMoN/qiwNuGZqQpUnQtYcunDdqqNmnc11qSUve6VLHs9L7"
    "1uY+Tqdt56tn8bvbo2GyzhBYuvc6xLgifHGR6AB8HTkKn2fin48NgjCo7Qhz272D6vqoDj"
    "4Ic98u1UZzw4QIHmJI/pFFYZYSIbpqovfg6z2qq+9051hwicQcbsKX9yiPWICHorNKZvVX"
    "dIaLH3VK2qUW+uNytsREZD26VkoMKfuO9wzVNnsTYDa/GdVqc+fKeY4jFvJauOCYfNZpGc"
    "nTPbbWLuBNccu5HAq0BnoTdZIirSdHUkKwSpI4SRVRU6msKDoX8gY/YCf09PT49PkAbNJx"
    "J6WaAnIsn4afAZYQOpUI+GzclpxQfebu4QQi9+WT4/H3PWnSp/lpzjHjlHuxcCyK5hDByR"
    "A2QeL6oxCIOLaiRfwLK8myxDnekiEWa6kgRlr9QBAn1+Vr2MQ4FBsWgOjGf6CQMxlAJbS8"
    "44QiU3k4CbMQ1NgLtSQ1P1EJUjenQHJbMb4RVT1CrZDPE45ON5NPd4HqAeDRObsxC9mSHd"
    "pLMpR7sFTcJUJME5ZSWdIdrPnVq/33rXaTYSgg6Sj53up84dWl4MqVMXS7Svh9RJddLq3U"
    "6nWR+0Ou/ukHM9pK1Gu3mH2N8h7Q96zdoTL7K6HNJes97tNXjq6nJIWUtdOZ6fQ9po9Wv3"
    "bdYC+8qvZO1p8eFdDpibWE62/vgFD884cHUeB24oFYk3z/MC/rIwiSHAekLkt1AbgTyOVF"
    "qDstlR1me7VWB/q1YvLm6qZxfXt1eXNzdXt2crTTaYtU6lvW+9YwuRp0OCK5OCDVNYDuHk"
    "NGdQegtUZ85eheIym0FC2+oviwVK3d0e8bK/89zfSxIlESHgkcluWs05NRAwEPhBDiL8oO"
    "pEHtNHsggom+toxAICHMUeQrKO5yuGyju0mL2ZKMTaMtVr/Xqt0az8iLa7JGJ6E9KWnJrr"
    "wHUlhLN0Mk/WEZZTVgzeRMAwFltZuhvm6f0+WUP97dfdcL/QevYB13F4qOtoFuo6wEFhTU"
    "7K97lEDpDs24kfljU1TUC5SAK0V6rEOh7WnLALZ/miPbDcMtmpXLdXV5e5npIdVCeKkRRU"
    "t0iGmMK/gmA6Jy+6KSaF1SeVKbK/FQRZEWtYlM2F4Ao/ib37Copmh/H52Y7Zra1BzNx+QJ"
    "cXvs1U0No4H5iMQoyoIBXWOWMw9sMkvhHdCA0YidYwXCKHR5pvX1nmCtnU/C6kgDpMtsR8"
    "M+aM3I7Y/MUzI2bs/lHpNWuN/yQ1IHIhZsSD/4a0Vh+0PjbvkPX/kDZ6tVaH2/LsK2Y07D"
    "W63JBoXzGjI1QAQN4zu6Hrx5B2Hx7arQ6kLi/SmPy2byPmdPaEYN18ITg1H+6voGTE88yI"
    "Twk8qxiiK/ze73aips6ViL9vZdFE/0OKbBRQS1jTqwwLT4cGQhv9UYy+nmIV+EMbdTIGnI"
    "ieKp4iIFyGVOTltSsDaX7FXt9qIM0b6+7QDVyCKIe+taH7yOsq4EAoTCRNPtexuLhtJVzr"
    "IEM9ysCjnQUeJTRHe6eyEJN0YK6LNkvbPJdrjt0cSFNDmoJFguYTULkQRpw9QMy2jaZ4gV"
    "idBOl27xp3UGSkKhLRkUrhWlFFrCBJl98IUnVIoMScq/orMmDbTIJRNbu93ZAO6YOsKEim"
    "kA1S0IMTYlVvVWogU+VpI1k3TGRBhY4UdU7g51dYFmWGzNdjKIRNJBsIiyIBtOj4BHUfEa"
    "bSkFLVRA/P7fYJ+wkNUxZIfSP6XJdNYvDaWZOhPudBoBQ8NYFSC/umUPcIBsMp6rifYUhF"
    "UH1ZlD70F4IEeESQspCREIPtn+wWC55n4DfCWuA85oc6OvoEb5A6N1B9VRN64gNQP46OQq"
    "JLtwcWq1QGIO03AIl1QQDWdeeVWOUP0HB7eXYWgwuCUpFkEM/znQmzfMsTDF23yME4IG/N"
    "RJPaNFOaZLZkklmtUiH4rwvy8siVcV7x47xkY9XyZIh7BTOEfJVSWMwLZ6H50OywUKikNp"
    "ql2B1aXgxp9/EOtE9QbkHrvOO6Jw/8+lhrtW0bzOrHkDZ7vW7vDvH/8mF/4eCnjLhyyx2e"
    "HXMnnmkmrKpKmvXYJ1iux2nX45FOSJoO8MqV+KfF39l5p+mFMOmyL9L2BeNFkmumLqlSSU"
    "qgJHFPBZ0wr820fg4e6dLJIT92t6C5tTytMnqyK6a5tTSy/4q9HmVkd/c6Y+iTBfi6JMrw"
    "3s3hvbYJ5CeDez1RpAVDOG58r2tkJY3uzYHpOZ8KSbaW56A/SIj1OdRpJNoCHe6zUsZHF2"
    "qCPFljmVxiEWo7W7eh9sod0lqUOa+BjWThII7EAZqHdxIFoqdTrb2SB6haF1eVDu6gCECY"
    "ppPdciUzkuceLg9E2p5CsM89aM5ekfKEqZzsQGOcMOUfuBnv7XM2cn92aw/3R53ndntfJ3"
    "cF/PEjPzrg9dnf+OEBX8TAZp/pTxNZnLhdl9U5NdARO//fQH+zPY2PV18LOEXsYwK6Okca"
    "0ZdpJ+iVaCYawQB8I1wR9/hJb/8WQ2qo6KuzEfsKuUQzkMwcjrEB90VY1FXDQFP1jRhRjs"
    "Ll9rvcfufFfzXrA3ThNSEC+a7JoKamsa2GyJd7iDzvITJnW3LWl7smW0rrdTT0xbRjltbr"
    "X7HX82m9zttkuvWj53JBcBVe4c6XQ0DOBu1+SIPNfJj9xcads2F7Hd5b5MK2x8ME/C1CeJ"
    "gwn4xoHmblbi24PUI28zAt1inss4zsG4tWJURC4mRGX9HR6OnDJWIf5Tu2Y6d5BLlDqZyi"
    "j/zzjtzDOzzSOhi/ns0tN/MuX3xTufP9QW6GFLj+AzJfXB+4IlRapidibZ6fW40EtM1sJk"
    "unTGY3b1vlX6MZFdkIQPxO7M/lvyu7fQHDFg/ru1OWQuVWlfijlx+YTLSz3P43vkqmbJ9M"
    "mWsOCqAfw4liJXmAO7zi7uhCnShSdbJbruziXHexNLNmQ2Ga5Ghzn1TpSRE2R8r/TRUh6p"
    "U7JGgzXqREUMjFJDrYSuDwqP3tK2BMWxWSHmTkETpAPXcnX1fVQGNKdMrxSuCnzjjOG9Jr"
    "gN3JIccF/Oz06oiQhNvliuugEdcxI41mu2l9S9q+8tMlcd6J7R82UloVo6Evpn0pjlUxJ+"
    "aQfXdw4f19Dx1R6/TPZJh6ZEpbaOlF/Qt5URcV2Y0R0sFJYQvIJj0aP2fzQlxwPRNirrzU"
    "a0SXxUklLJbayjlZG0DtlCmDpou0GJ2sMfft4XN5eZs0/WceXsXY80GpNWceXgW/L60lQX"
    "hZ/ADRPY91ZPb5miOzz4NHZsMdzaUfR1yaySVSEk0JiaaAbpvlYvbj/628QgA="
)
