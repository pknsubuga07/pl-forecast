import "server-only";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { FixtureDetail, FixtureSummary, History, Meta, Performance, TableRow, TeamPage } from "./types";

// The pipeline writes these files; the build reads them. Nothing is fetched at runtime.
const DIR = path.join(process.cwd(), "public", "data");

const cache = new Map<string, unknown>();

function load<T>(name: string): T {
  if (!cache.has(name)) {
    cache.set(name, JSON.parse(readFileSync(path.join(DIR, name), "utf8")));
  }
  return cache.get(name) as T;
}

export const getMeta = () => load<Meta>("meta.json");
export const getFixtures = () => load<FixtureSummary[]>("fixtures.json");
export const getFixtureDetails = () => load<Record<string, FixtureDetail>>("fixture_details.json");
export const getTable = () => load<TableRow[]>("table.json");
export const getTeams = () => load<Record<string, TeamPage>>("teams.json");
export const getHistory = () => load<History>("history.json");
export const getPerformance = () => load<Performance>("performance.json");
