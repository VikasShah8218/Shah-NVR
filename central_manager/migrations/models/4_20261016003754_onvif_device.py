from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" ADD "onvif_port" INT;
        ALTER TABLE "cameras" ADD "firmware" VARCHAR(128);
        ALTER TABLE "cameras" ADD "clock_offset_seconds" DOUBLE PRECISION;
        ALTER TABLE "cameras" ADD "onvif_services" JSONB;
        ALTER TABLE "cameras" ADD "serial" VARCHAR(128);
        ALTER TABLE "cameras" ADD "onvif_host" VARCHAR(255);
        ALTER TABLE "cameras" ADD "onvif_reachable" BOOL;
        ALTER TABLE "cameras" ADD "manufacturer" VARCHAR(128);
        ALTER TABLE "cameras" ADD "model" VARCHAR(128);
        ALTER TABLE "cameras" ADD "mac" VARCHAR(32);
        ALTER TABLE "cameras" ADD "onvif_checked_at" TIMESTAMPTZ;
        ALTER TABLE "camera_streams" ADD "onvif_profile_token" VARCHAR(128);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" DROP COLUMN "onvif_port";
        ALTER TABLE "cameras" DROP COLUMN "firmware";
        ALTER TABLE "cameras" DROP COLUMN "clock_offset_seconds";
        ALTER TABLE "cameras" DROP COLUMN "onvif_services";
        ALTER TABLE "cameras" DROP COLUMN "serial";
        ALTER TABLE "cameras" DROP COLUMN "onvif_host";
        ALTER TABLE "cameras" DROP COLUMN "onvif_reachable";
        ALTER TABLE "cameras" DROP COLUMN "manufacturer";
        ALTER TABLE "cameras" DROP COLUMN "model";
        ALTER TABLE "cameras" DROP COLUMN "mac";
        ALTER TABLE "cameras" DROP COLUMN "onvif_checked_at";
        ALTER TABLE "camera_streams" DROP COLUMN "onvif_profile_token";"""


MODELS_STATE = (
    "eJztXetz2joW/1c0fEpms9mE5nWzOztDgLTcEugAabu33HEVW4AnRqa2CWXv9n/fI9nGb2"
    "O7QGzX/ZAaSUeWf0ePo/OQ/qrNVYko+mkTz4mGa7forxqFR3jw5ZygGl4snHSWYOAnhRcV"
    "eRmehp90Q8OiAckTrOgEkiSii5q8MGSVQipdKgpLVEUoKNOpk7Sk8rclEQx1SowZ0SDjy5"
    "+QLFOJfCe6/XPxLExkokietsoSezdPF4z1gqd1qHHPC7K3PQmiqizn1Cm8WBszlW5Ky9Rg"
    "qVNC4UsMwqo3tCVrPmud9aH2F5ktdYqYTXTRSGSCl4rh+twnwUmrCUKvPxKG7ZEg1FIAJK"
    "qUgQtN1fnXT1kT/l4/v7i+uHlzdXEDRXgzNynXP8xXO8CYhBye3qj2g+djA5slOMYOqPz/"
    "AKzNGdbCcbXL+5CFJvuRtXGMg9ZOcLB1+tMhwJ3j74JC6NSYwc/z+k0MlB8bg+a7xuAISh"
    "2zV6owAMyB0bOy6mYew9vB192yAMwj8j2i+/rIMqFtddO8gB2D7aj9ecRqnuv6N8UN6dFD"
    "4zNHe762crr93lu7uIsFzW7/zof8Uida2t7tpikD5gfo4Aus6ytVC5mbo2F205QP5vrlVQ"
    "KYoVQkzDzPCzOh7NNDUL5TVYVgGg60i8qH8xOQ7WvGttfHw04id/1+1zOJ3HX8s8Tjw10b"
    "OjjHHQrJBnEvkg7YGjEIZU0TJLzWU0gdQcLtEsiOuvd1rgUQB1uVvsgTYabqRpoZw0tVxj"
    "njMtGccRkzZ1z65wwTtIWqhUAd2YW9RAfrvrkXoV17JkyXE9j9LDWipenDfrry9eK9CBh8"
    "K5oKZ5ugAjgRwBNZm6+wlkpQdtNUMCeCGbYWMk7VkR2KCuJkUwUW003IYjnBfVNPgO2bei"
    "S0LCtMlIAO+SKLJEQi/n3Y78XJE25KH96SLBrof0iR9QLKFjE4M0jilRp+/QXDBiTcqcZr"
    "4RX4lRommhrB4owDEmBE7HYwhDrbtrA4XNjhrlBUVPFZUCcTnRjQoaENUshIuFdUHCFaR1"
    "Xg48GE1VAqJrT6j3fdNvowaDc7w441LGyNnpnpBX/QbnRDe744I+IzkQQcsqVpAVSGPCdx"
    "fd9L75+JrApO7YdSMWHUeWgPR42HD57h0GqM2iyn7uWJlXrk11FtKkGfOqN3iP1Ef/R7bf"
    "/ctSk3+qPG2oSXhipQdSVgyY2JnWwneccbTFRGJl57KXfA5dwZLuADpT5V1lYPLAjbrcES"
    "y/XlQsrIdS9lxfW8cD1ksPPWM0Pv5NlllWQJT1h8ho2lJHhyXLsoA0CYh6y7dxbh/fsBUX"
    "CE4cxj7h7yqgrYD37YPd9OdfqDAxTWdXlK54QawgxEa1Vb/xxmjU1975zqygicTqbsK3+y"
    "iw1AvNMkaMzQrK5MaLFxqtbVqJHrzQrrkdHQ9ikZqfAn6RhueOospKwWju+8PvfhO8cUT3"
    "krWXWMOGw2i3TucWa7bS4+gmuO3erpUwNmoRdZIipaaOpEVghSJwgjsyp0NIcPQ/9A+vIJ"
    "/p6enh6foAU0n0joaY0eiCTjh9FnhHWkQj0LbMxOaz7w9vOGED+kL9b38z5nvqn2Z+Wc9I"
    "rOSTYXAsjGuBY4JCV0Udq9Yk9Xl5pIhKWWTjPtoSoh0Odn9Ysk+mkoFq2g5pl+zwIx1Fcm"
    "Vm3nEFVOHCmcOAx9IcBbqR5uAY/u3UHKw/XwmiEuaofp4km8lM6jnZTOAz5KluuAOQPD0v"
    "pMQnwet/l4BMjLZ57Zj3nRwMYyZNPC8G7T5Zxj3oFWYSqS4IS+oT5gV3/sNYbDztteu5Wy"
    "xwPl+17/U+8WWQ9j6tTFEu3nMXVSnbRmv9drN0ed3ttb5DyPaafVbd8i9ndMh6NBu/HAi2"
    "wex3TQbvYHLZ66eRxT1lJXjufnmLY6w8Zdl7XAfvJLuK+08nOWA+YGltMt/n7C8o3Qy/Mk"
    "cEOpSLx5nhfwp7VBdAEWcyK/hHpyytPIHUOQNpNnVqZxerbf3cNv9fqbN9f1szdXN5cX19"
    "eXN2ebbUQwK24/cdd5y6QAD0OCYoGCdUOwunB6HXOQurIh5UetHLQmmPwyVXCZ2e0hr/id"
    "Z35bGqxU2hgPzeGm1ZzrZQLWGT/IQYTvVY3IU/qerAPCZpwOt4AAR6luIVnDq4160Nu1WF"
    "QAUYi5X202hs1Gq137EW30SqVmT6kz5nrRHjzXQhTGTuZJnLZ4zorBSJRIFRRaLr3r6waF"
    "vi60nn3AVRIl4FW0CvAqoADECzmtstVFUkJN616i5cypKW2QkZeqwjoZ1lxbmjLIyENzOJ"
    "Hr5vLyItdTsoPqTNHTguomOSCm8K8gmK7Ik2aIaWH1UR0U2d8KgqyIF1iUjbXgOiQk8e4r"
    "SHo4jM/P9qzd2hnEzOcKZHnh21IFqY3rA9OpECMqKFGE54E1iS9E00OP9YiWMFwk5VOa71"
    "5Y5gLZ3PguZIA6jLbCfDvmTLkdsflLZkY8sO8NixVp/SetAZETMSMe/Demjeao87F9i8z/"
    "x7Q1aHR63JZnPzGj4aDV54ZE+4kZHaECAPKO2Q1dP8a0f3/f7fQg1XrIYvLbvYGeq7NnBG"
    "vGE8GZ9eH+CiqNeJ414nMC3yqmCtl0kVSxmtljNTUyBZyIlimYJUBcxbPkZdhVUUy/Itd3"
    "GsX0wtgduoFLEWIyNDd0H3ldBewIhQljyuc6lhS3ncTKlTLOpor62lvUV0pztHcqCzFJB+"
    "a6aLO0redyzbHbo5gaaKFgkaDVDEQuhBHXHiBm20ZzvEasToI0m7v6LRSZqIpENKRSeFZU"
    "EStI0uQXglQNEigxVqr2jHTYNpNgSNN+XzemY3ovKwqSKWQDFXBwRszqzUp1ZKg8bSJruo"
    "FMqNCRoq4I/PwKy6LMkPl6DIWwgWQdYVEkgBadnqD+e4SpNKZUNdD9Y7d7wn5Cw5Q1Ul+I"
    "ttJkg+i8dtZkqM/5ECgFX02g1Np+KdQ9gc5winrubxhTEURfdpYi8AtBAnwiUJnISIjB9k"
    "/2ijXP0/ELYS1wPvNDEx19ghGkrnTU3NSEHngH1I6jQ8Co5fbAAsWq6K/Xjf5iLAjAGneq"
    "rFm+hIbbi7OzBLogKBWpDOJ5vpN7rVGeouu6SUrjgLwzE01m00xlktmRSWazSoXgHxdh56"
    "GrguySB9nJ+qbl6RD3Eh4Q8k1KYTEvnIXmQ7vHQqHS2mgssltkPYxp//0tSJ8g3ILUectl"
    "Tx749bHR6do2mM2PMW0PBv3BLeL/5cP+wsHPGHHlpiufHXMvnmkGrKpKlvXYR1itx1nX44"
    "lGSBYGeOkq/LPi7+y8s3AhjLriRVZeML1IesnURVUJSSmEJO6poBHmtZnVz8FDXTk55Mfu"
    "FjS3VkeFRk92xTS3Vkb2X5HrUUZ2N9eZhj5dgK+Logrv3R7ea5tAfjK41xNFWjCEk8b3un"
    "pW2ujeHJie8ymQHNbyHPQHCbE+hzqNRFugw31WqvjoQk2QJzGWSQuLUNtZ3IbaS1emtejg"
    "eg2spwsHcShKaB7eSxSIlk209lKWULQurigd3EERgDALk910lWYkzxyuDkTanUDwmnvQnA"
    "2R6oSpnOxAE5ww5e+4B97b56zn/uzWHt6Peo/d7mud3BXwx4+88cHrs7/11gdfxMB2n+lP"
    "M1mcuV2X1RXV0RG7fEFHf7M9jY83VzWcInaTg6au0IJoVtoJeiYLA02gA76YtyJ7/KR3/4"
    "ox1VX01dmIfYVcstCRzByOsQ7vRVjUVF1Hc/WF6FGOwtX2u9p+58V/9dAH6MIwIQL5vpBB"
    "TM1iWw2hr/YQed5DHFzbkjNe7lvZUlmvo6Evph2zsl7/ilzPp/U6b5Ppzo+ey4WCq/ACd7"
    "4cAnLWaV9HabBdH2Zfl7l3bdirdu8d6sJ2p4cJ+FuE6GHCfDKi9TAbd2vB7RGyXQ/TYUxh"
    "d2KyCy7NSoiExNmSPqOjycOHC8Qu1Dq2Y6d5BLmjUjlFH/ndmtzDOzzSOhi/fphXbte7fP"
    "FN5c7lj9wMKXD5B2i+uC64IlSy0lNpbR4fO60UapvlUpZOGc1+RlvtX5MlFVkPQPxN7M/F"
    "v2v7HYBhi4d575QpULlFJf7p1e2eqXaWu7/jq9KUvaamzDUHBdBP4ESxoSzhDq+4O7pQJ4"
    "pMTHbTVSzONYulpTkbCvM0R5v7qCpPirA5Uv5vpghRL12ZoD3wIiWCQC6mkcE2BOVT7e9e"
    "AONXGac9yMhDVEI5dy+3qy5AYkp1yvGG4KfOOM4b0jHA7uWQ4wJeO705IiTldrnmOmjEdc"
    "xIq91tm3dJ209+dUmSMbH7w0Yqq2I09MW0LyWxKubEHPLaDC68v2/ZETVP/0yHqYemsoVW"
    "XtS/kBd1UZHdGiEdnBR2gGzao/FzNi8kBdczIebKS71BNFmc1cJiqc2ck9gAaqdMFTRdpM"
    "XoJMbc9wrX5eVt0vSfeXiZYM8HpWLOPLwM3i+9SIOwVbyE6J4nOjL7PObI7PPgkdnwRsPy"
    "40iqZnKRVIqmlIqmgGx7yMXsx/8BYkflRA=="
)
