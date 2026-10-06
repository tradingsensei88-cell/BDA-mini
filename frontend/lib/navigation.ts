import {
  Activity,
  BarChart3,
  Bell,
  Brain,
  GitBranch,
  LayoutDashboard,
  Network,
  Search,
  Settings,
  ShieldAlert,
} from "lucide-react";
import type { NavigationItem } from "@/types";

/**
 * Primary SOC navigation.
 *
 * Badge counts are mock values for the shell build; Task 8+ will bind them
 * to live alert / threat counters from the API.
 */
export const NAV_ITEMS: NavigationItem[] = [
  { name: "SOC Overview", href: "/overview", icon: LayoutDashboard },
  { name: "Live Network", href: "/network", icon: Network },
  { name: "Threat Detection", href: "/threats", icon: ShieldAlert, badge: 5 },
  { name: "Security Alerts", href: "/alerts", icon: Bell, badge: 12 },
  { name: "Attack Analytics", href: "/analytics", icon: BarChart3 },
  { name: "ML Intelligence", href: "/ml", icon: Brain },
  { name: "Investigations", href: "/investigations", icon: Search },
  { name: "Data Pipeline", href: "/pipeline", icon: GitBranch },
  { name: "System Health", href: "/health", icon: Activity },
  { name: "Settings", href: "/settings", icon: Settings },
];
