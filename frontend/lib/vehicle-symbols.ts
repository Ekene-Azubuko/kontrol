export type VehicleSymbol = "ambulance" | "police" | "fire" | "rescue";

/** Normalize the fleet's vehicle types into consistent map and card symbols. */
export function vehicleSymbol(type: string): VehicleSymbol {
  if (type === "ambulance") return "ambulance";
  if (["police", "police_car", "police_vehicle"].includes(type)) return "police";
  if (["fire_engine", "fire_truck", "fire_rescue"].includes(type)) return "fire";
  return "rescue";
}

export const vehicleSymbolLabels: Record<VehicleSymbol, string> = {
  ambulance: "Ambulance",
  police: "Police car",
  fire: "Fire truck",
  rescue: "Rescue unit",
};
