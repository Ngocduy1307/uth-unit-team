package vn.unit.affordability.financial.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EvaluateAffordabilityRequest {

    @NotBlank
    private String dossierId;

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal eligibleNetIncome;

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal declaredLivingExpenses;

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal floorLivingExpenses;

    @NotNull
    @DecimalMin(value = "1000000")
    private BigDecimal proposedLoanAmount;

    @NotNull
    @Min(1)
    private Integer proposedLoanTenorMonths;

    @NotNull
    @DecimalMin(value = "0.01")
    private BigDecimal proposedInterestRate;

    @NotBlank
    private String calculatedBy;
}
