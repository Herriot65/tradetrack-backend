"""Benchmark CPU and wall time with synthetic inputs; no database writes."""
import json
from statistics import median
from time import perf_counter, thread_time

from django.contrib.auth.hashers import PBKDF2PasswordHasher, get_hasher
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compare the configured password hasher with PBKDF2 using synthetic data."

    def add_arguments(self, parser):
        parser.add_argument("--samples", type=int, default=7)

    def handle(self, *args, **options):
        count = options["samples"]
        if not 1 <= count <= 50:
            raise CommandError("Choose between 1 and 50 samples.")
        report = []
        for hasher in (PBKDF2PasswordHasher(), get_hasher()):
            encoded = hasher.encode("synthetic-benchmark-password", hasher.salt())
            wall, cpu = [], []
            for _ in range(count):
                started, cpu_started = perf_counter(), thread_time()
                if not hasher.verify("synthetic-benchmark-password", encoded):
                    raise CommandError("Synthetic password verification failed.")
                wall.append((perf_counter() - started) * 1000)
                cpu.append((thread_time() - cpu_started) * 1000)
            report.append({"algorithm": hasher.algorithm, "samples": count,
                           "median_wall_ms": round(median(wall), 1),
                           "median_thread_cpu_ms": round(median(cpu), 1),
                           "iterations": getattr(hasher, "iterations", None),
                           "time_cost": getattr(hasher, "time_cost", None),
                           "parallelism": getattr(hasher, "parallelism", None),
                           "memory_kib": getattr(hasher, "memory_cost", None)})
        self.stdout.write(json.dumps(report, indent=2))
