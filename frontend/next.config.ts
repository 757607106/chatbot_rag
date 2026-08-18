import type { NextConfig } from "next";

const configuredDevOrigins = (process.env.CHATBOT_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter((origin) => origin.length > 0);

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", ...configuredDevOrigins],
  poweredByHeader: false,
  reactStrictMode: false,
};

export default nextConfig;
